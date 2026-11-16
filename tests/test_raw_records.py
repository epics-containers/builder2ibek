"""
Raw records.* components: every one but an EtherIP ao goes to records.db next
to the ioc.yaml, in builder's own <IOC>.db layout, and an epics.StartupCommand
loads it.

raw_records/BL03I-VA-IOC-02.xml is the builder XML of that IOC, with its PLC
address replaced by loopback; raw_records/BL03I-VA-IOC-02.db is the <IOC>.db
builder made from it.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

HERE = Path(__file__).parent / "raw_records"
SCHEMA = "/epics/ibek-defs/ioc.schema.json"
LOAD = {"type": "epics.StartupCommand", "command": "dbLoadRecords config/records.db"}

IOC = "BL01C-VA-IOC-01"

XML = r"""<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <asyn.AsynIP name="MIRRORport" port="127.0.0.1:7001"/>
  <ether_ip.EtherIPInit device="BL01C-VA-VLVCC-01" ip="127.0.0.1"
    name="VLVCC_01.INFO" port="VLVCC_01_EIP"/>
  <records.ao DTYP="EtherIP" OUT="@VLVCC_01_EIP GB_Index_Setpoint S 0.5"
    name="GB.IDXSP" record="BL01C-VA-VLVCC-01:GB:IDX_SP"/>
  <records.asyn ADDR="0" AOUT="GROUP0:STATUS?" DTYP="asynRecordDevice"
    IEOS="\\r\\n" IMAX="80" OEOS="\\r\\n" OMAX="80" PINI="YES"
    PORT="MIRRORport" record="BL01C-OP-MFM-01:ASYN"/>
  <records.bo DTYP="EtherIP" OUT="@VLVCC_01_EIP RESET" name="BO"
    record="BL01C-VA-VLVCC-01:RESET"/>
  <records.calcout CALC="A" INPA="BL01C-EA-DET-05:CAM:Acquire CP"
    name="LED_DISP" record="BL01C-EA-TABLE-01:LED:DISABLE"/>
</components>
"""

RECORDS_DB = """\
# Raw records from the records.* elements of BL01C-VA-IOC-01.xml,
# loaded by an epics.StartupCommand in ioc.yaml.

record(calcout, "BL01C-EA-TABLE-01:LED:DISABLE")
{
    field(CALC, "A")
    field(INPA, "BL01C-EA-DET-05:CAM:Acquire CP")
}

record(asyn, "BL01C-OP-MFM-01:ASYN")
{
    field(ADDR, "0")
    field(AOUT, "GROUP0:STATUS?")
    field(DTYP, "asynRecordDevice")
    field(IEOS, "\\r\\n")
    field(IMAX, "80")
    field(OEOS, "\\r\\n")
    field(OMAX, "80")
    field(PINI, "YES")
    field(PORT, "MIRRORport")
}

record(bo, "BL01C-VA-VLVCC-01:RESET")
{
    field(DTYP, "EtherIP")
    field(OUT,  "@VLVCC_01_EIP RESET")
}
"""


def _convert(xml: Path, yaml: Path) -> tuple[list[dict], list[str]]:
    warnings = convert_file(xml, yaml, SCHEMA).warnings
    return YAML(typ="safe").load(yaml.read_text())["entities"], warnings


def _write_xml(tmp_path: Path, text: str) -> Path:
    xml = tmp_path / f"{IOC}.xml"
    xml.write_text(text)
    return xml


def test_records_db_matches_builder(tmp_path: Path):
    """records.db holds what builder wrote to <IOC>.db, byte for byte"""
    _convert(HERE / "BL03I-VA-IOC-02.xml", tmp_path / "ioc.yaml")
    ours = (tmp_path / "records.db").read_text()
    builders = (HERE / "BL03I-VA-IOC-02.db").read_text()
    ours_header, _, ours_records = ours.partition("\n\n")
    builders_header, _, builders_records = builders.partition("\n\n")
    assert ours_records == builders_records
    assert "BL03I-VA-IOC-02.xml" in ours_header
    assert all(line.startswith("#") for line in builders_header.splitlines())


def test_records_db_contents(tmp_path: Path):
    _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    assert (tmp_path / "records.db").read_text() == RECORDS_DB


def test_backslash_escapes_decoded(tmp_path: Path):
    r"""The XML's \\r\\n is written as \r\n, as builder wrote it"""
    _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    text = (tmp_path / "records.db").read_text()
    assert 'field(IEOS, "\\r\\n")' in text
    assert "\\\\" not in text


def test_hardware_dtyp_records_written(tmp_path: Path):
    _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    text = (tmp_path / "records.db").read_text()
    assert 'record(asyn, "BL01C-OP-MFM-01:ASYN")' in text
    assert 'record(bo, "BL01C-VA-VLVCC-01:RESET")' in text


def test_startup_command_loads_records(tmp_path: Path):
    entities, warnings = _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    assert not [e for e in entities if e["type"].startswith("records.")]
    assert entities[-1] == LOAD
    assert entities.count(LOAD) == 1
    (note,) = [w for w in warnings if "raw records" in w]
    assert note.startswith(f"{IOC}: 3 raw records written to config/records.db")
    assert not [w for w in warnings if "won't convert" in w]


def test_ether_ip_ao_unchanged(tmp_path: Path):
    entities, _ = _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    (ao,) = [e for e in entities if e["type"] == "ether_ip.ao"]
    assert ao == {
        "type": "ether_ip.ao",
        "record": "BL01C-VA-VLVCC-01:GB:IDX_SP",
        "port": "VLVCC_01_EIP",
        "tag": "GB_Index_Setpoint S 0.5",
        "scan": "Passive",
    }
    assert "GB:IDX_SP" not in (tmp_path / "records.db").read_text()


def test_stale_records_db_removed(tmp_path: Path):
    """With no raw records, xml2yaml removes records.db and nothing else"""
    no_records = _strip_records(XML)
    keep = tmp_path / "keep.db"
    keep.write_text("keep")
    (tmp_path / "records.db").write_text("stale")
    entities, warnings = _convert(
        _write_xml(tmp_path, no_records), tmp_path / "ioc.yaml"
    )
    assert not (tmp_path / "records.db").exists()
    assert keep.read_text() == "keep"
    assert LOAD not in entities
    assert not [w for w in warnings if "raw records" in w]


def test_records_db_kept_when_written(tmp_path: Path):
    (tmp_path / "records.db").write_text("stale")
    _convert(_write_xml(tmp_path, XML), tmp_path / "ioc.yaml")
    assert (tmp_path / "records.db").read_text() == RECORDS_DB


def _strip_records(xml: str) -> str:
    """The XML without its records.* elements, which span several lines"""
    lines, skipping = [], False
    for line in xml.splitlines():
        if line.lstrip().startswith("<records."):
            skipping = True
        if not skipping:
            lines.append(line)
        if skipping and line.rstrip().endswith("/>"):
            skipping = False
    return "\n".join(lines)
