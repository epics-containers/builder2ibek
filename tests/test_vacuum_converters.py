"""
Converter fixes for vacuum IOCs: XML attributes that parse as numbers but are
str in the model, leaf entities that must drop name, GUI-only templates that
create no records, and raw records, which are dropped with a warning.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

IOC = "BL01C-VA-IOC-01"

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <LeyboldTurbo.LeyboldPortDriver name="LEYBOLD_TURBO" num_pumps="1"
    port="LEYBOLD_TURBO" pzd_data_size="6"/>
  <LeyboldTurbo.LeyboldTurboPump addr="0" name="TURBO1" p="BL01C-VA-TURBO-01"
    port="TSERV1_6" port_driver="LEYBOLD_TURBO"/>
  <dlsPLC.fastValve addr="70" device="BL01C-VA-FVALV-01" gilk0="Gauge 07"
    gilk1="" ilk0="Remote Mode" ilk1="" ilk10="12" mode1="" mode2="0"
    name="FVALVE1" port="VLVCC2" vlvcc="BL01C-VA-VLVCC-02"/>
  <userIO.auto_calcout12input CALC="A" DOPT="" EGU="" FLNK="" INPA="1"
    INPB="BL01C-VA-VALVE-10:STA" OCAL="1" OOPT="" OUT="" P="BL01C-VA-SPACE-12:"
    PREC="3" R="1" SCAN=".5 second" name="BL01C-VA-SPACE-12:"/>
  <alarmMonitor.alarmMonitor ALARMSTAT="LOW LEVEL" CONDITION="A&lt;B"
    INPA="BL01C-VA-PIRG-81:PRESSURE3_RBV" INPB="1e-03"
    P="BL01C-VA-PIRG-81:PRESSURE3" R=":LOWLEVEL" name="PIRG81ALH.LOW"/>
  <alarmMonitor.alarmNoAck ALARMSTAT="maintenance required" CONDITION="A=1"
    DISABLELINK="0" DISABLEVAL="0" INPA="BL01C-VA-O2-01:SENS:MAINTAIN" INPB="2"
    P="BL01C-VA-O2-01" R="1" name="AL1"/>
  <FINS.FINSTemplate device="BL01C-VA-VLVCC-03" name="VLVCC3.INFO"
    port="fins_VLVCC3"/>
  <digitelMpc.digitelMpcqTsp ctlsrc="1" device="BL01C-VA-TSP-01" name="TSP1"
    port="vts_MPC1" unit="01"/>
  <digitelMpc.digitelMpcTspGroup device="BL01C-VA-GTSP-01" name="GTSP1"
    tsp1="BL01C-VA-TSP-01" tsp2="BL01C-VA-TSP-01" tsp3="BL01C-VA-TSP-01"
    tsp4="BL01C-VA-TSP-01" tsp5="BL01C-VA-TSP-01" tsp6="BL01C-VA-TSP-01"
    tsp7="BL01C-VA-TSP-01" tsp8="BL01C-VA-TSP-01"/>
  <rga.rgaGuiTemplate device="BL01C-VA-RGA-01" name="rga_gui"/>
  <insertionDevice.idcpmuVacuumGui name="gui" prefix="BL01C-VA-" cell="BL01C"/>
  <insertionDevice.idcpmu5VacuumGui name="gui5" prefix="BL01C-VA-"
    cell="BL01C"/>
  <records.calcout CALC="A" INPA="BL01C-EA-DET-05:CAM:Acquire CP"
    name="LED_DISP" record="BL01C-EA-TABLE-01:LED:DISABLE"/>
  <records.calcout CALC="A" INPA="BL01C-EA-TABLE-01:LED:TOGGLE CP"
    name="DET_DISP" record="BL01C-EA-DET-05:CAM:DISABLE"/>
  <records.ai name="AI" record="BL01C-EA-TABLE-01:AI"/>
</components>
"""

VXWORKS_XML = """<?xml version="1.0" ?>
<components arch="vxWorks-ppc604_long">
  <DLS8515.DLS8516channel card="BL01C-VA-IOC-01.Slot4.D" channel="0"
    fullduplex="True" name="SER.4D0"/>
  <DLS8515.DLS8516channel card="BL01C-VA-IOC-01.Slot4.D" channel="1"
    name="SER.4D1"/>
</components>
"""


def _convert(tmp_path: Path, xml_text: str) -> tuple[list[dict], list[str]]:
    xml = tmp_path / f"{IOC}.xml"
    xml.write_text(xml_text)
    yaml = tmp_path / "ioc.yaml"
    warnings = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json").warnings
    return YAML(typ="safe").load(yaml.read_text())["entities"], warnings


def _by_type(entities: list[dict], entity_type: str) -> list[dict]:
    return [e for e in entities if e["type"] == entity_type]


def test_leybold_turbo_keeps_driver_name_only(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    (driver,) = _by_type(entities, "LeyboldTurbo.LeyboldPortDriver")
    (pump,) = _by_type(entities, "LeyboldTurbo.LeyboldTurboPump")
    assert driver["name"] == "LEYBOLD_TURBO"
    assert "name" not in pump
    assert pump["port_driver"] == "LEYBOLD_TURBO"
    assert pump["addr"] == 0


def test_dlsplc_numeric_labels_become_str(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    (valve,) = _by_type(entities, "dlsPLC.fastValve")
    assert valve["mode2"] == "0"
    assert valve["ilk10"] == "12"
    assert valve["addr"] == 70


def test_userio_calcout12input_fields_are_str(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    (calc,) = _by_type(entities, "userIO.auto_calcout12input")
    assert calc["OCAL"] == "1"
    assert calc["INPA"] == "1"
    assert calc["PREC"] == "3"
    assert calc["R"] == "1"
    assert "name" not in calc


def test_alarm_monitor(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    (alarm,) = _by_type(entities, "alarmMonitor.alarmMonitor")
    assert alarm["INPB"] == "1e-03"
    assert "name" not in alarm


def test_alarm_no_ack(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    (alarm,) = _by_type(entities, "alarmMonitor.alarmNoAck")
    assert alarm["R"] == "1"
    assert alarm["INPB"] == "2"
    assert alarm["DISABLELINK"] == "0"
    assert alarm["DISABLEVAL"] == 0
    assert "name" not in alarm


def test_leaf_entities_drop_name(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    for entity_type in (
        "FINS.FINSTemplate",
        "digitelMpc.digitelMpcqTsp",
        "digitelMpc.digitelMpcTspGroup",
    ):
        (entity,) = _by_type(entities, entity_type)
        assert "name" not in entity, entity_type


def test_gui_only_templates_dropped(tmp_path: Path):
    entities, _ = _convert(tmp_path, XML)
    types = {e["type"] for e in entities}
    assert "rga.rgaGuiTemplate" not in types
    assert "insertionDevice.idcpmuVacuumGui" not in types
    assert "insertionDevice.idcpmu5VacuumGui" not in types


def test_raw_records_dropped_with_warning(tmp_path: Path):
    entities, warnings = _convert(tmp_path, XML)
    assert not [e for e in entities if e["type"].startswith("records.")]
    record_warnings = [w for w in warnings if "records." in w]
    assert len(record_warnings) == 2
    assert any(
        w.startswith(f"{IOC}: won't convert 2 records.calcout entities")
        for w in record_warnings
    )
    assert all("config folder" in w for w in record_warnings)
    assert any(
        w.startswith(f"{IOC}: won't convert 1 records.ai entity")
        for w in record_warnings
    )


def test_dls8516channel_fullduplex_optional(tmp_path: Path):
    entities, _ = _convert(tmp_path, VXWORKS_XML)
    first, second = _by_type(entities, "DLS8515.DLS8516channel")
    assert first["fullduplex"] is True
    assert "fullduplex" not in second
