"""
Converters for accelerator vacuum IOCs: mks937a templates that the XML names as
builder auto_ classes, QPC ion pumps in the shapes of the QPC runtime pattern,
and raw EtherIP ao records, which become ether_ip.ao.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

IOC = "SR99C-VA-IOC-01"

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <asyn.AsynIP name="GCTLR01_PORT" port="127.0.0.1:7002"/>
  <mks937a.auto_mks937aImgMean current="SR-DI-DCCT-01:SIGNAL"
    device="SR99C-VA-MIMG-01" img1="SR99C-VA-IMG-01" img10="SR99C-VA-IMG-10"
    img2="SR99C-VA-IMG-02" img3="SR99C-VA-IMG-03" img4="SR99C-VA-IMG-04"
    img5="SR99C-VA-IMG-05" img6="SR99C-VA-IMG-06" img7="SR99C-VA-IMG-07"
    img8="SR99C-VA-IMG-08" img9="SR99C-VA-IMG-09" nimgs="10"/>
  <mks937a.auto_mks937aPirgDummy device="SR99C-VA-PIRG-99"/>
  <asyn.AsynIP name="MPC_A_04_PORT" port="127.0.0.1:7006"/>
  <QPC.digitelQpcIonp HV="7000" QPC="MPC_A_04" SIZE="300" SPLY="1" SPT="1"
    device="SR99A-VA-IONP-07" name="IONP_A_7" spoff="1.0E-4" spon="1.0E-10"/>
  <QPC.digitelQpc QPC="SR99A-VA-MPC-04" name="MPC_A_04" port="MPC_A_04_PORT"
    unit="a"/>
  <QPC.digitelQpc QPC="SR99A-VA-MPC-05" name="MPC_A_05" port="MPC_A_04_PORT"/>
  <QPC.digitelQpcIonp HV="5000" QPC="MPC_A_05" SPLY="2" SPT="2"
    alh="SR99A" device="SR99A-VA-IONP-08" name="IONP_A_8" spoff="1e-5"
    spon="1e-9"/>
  <QPC.digitelQpcIonp QPC="MPC_NONE" SPLY="1" SPT="1"
    device="SR99A-VA-IONP-09" spoff="1e-5" spon="1e-9"/>
  <ether_ip.EtherIPInit device="SR99C-VA-VLVCC-01" ip="127.0.0.1"
    name="VLVCC_01.INFO" port="VLVCC_01_EIP"/>
  <records.ao DRVH="3000" DRVL="0" DTYP="EtherIP"
    OUT="@VLVCC_01_EIP GB_Index_Setpoint S 0.5" PREC="2" SCAN="Passive"
    name="GB.IDXSP" record="SR99C-VA-VLVCC-01:GB:IDX_SP"/>
  <records.ao DTYP="EtherIP" OUT="@VLVCC_01_EIP CAVITY_RESET_01 S .2"
    PRIO="HIGH" VAL="1" name="CVRST_1" record="SR-RF-CVRST-01:CON"/>
  <records.ao DTYP="EtherIP" OUT="@VLVCC_01_EIP" name="BAD"
    record="SR99C-VA-VLVCC-01:BAD"/>
  <records.ao OUT="SR99C-VA-OTHER:VAL" name="SOFT" record="SR99C-VA-SOFT:OUT"/>
  <records.bo DTYP="EtherIP" OUT="@VLVCC_01_EIP RESET" name="BO"
    record="SR99C-VA-VLVCC-01:RESET"/>
</components>
"""


def _convert(tmp_path: Path) -> tuple[list[dict], list[str]]:
    xml = tmp_path / f"{IOC}.xml"
    xml.write_text(XML)
    yaml = tmp_path / "ioc.yaml"
    warnings = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json").warnings
    return YAML(typ="safe").load(yaml.read_text())["entities"], warnings


def _by_type(entities: list[dict], entity_type: str) -> list[dict]:
    return [e for e in entities if e["type"] == entity_type]


def test_mks937a_auto_templates_use_the_named_models(tmp_path: Path):
    entities, _ = _convert(tmp_path)
    assert not [e for e in entities if e["type"].startswith("mks937a.auto_")]
    (mean,) = _by_type(entities, "mks937a.mks937aImgMean")
    assert mean["device"] == "SR99C-VA-MIMG-01"
    assert mean["current"] == "SR-DI-DCCT-01:SIGNAL"
    assert mean["nimgs"] == 10
    assert mean["img10"] == "SR99C-VA-IMG-10"
    (dummy,) = _by_type(entities, "mks937a.mks937aPirgDummy")
    assert dummy == {"type": "mks937a.mks937aPirgDummy", "device": "SR99C-VA-PIRG-99"}


def test_qpc_controller_drops_name(tmp_path: Path):
    entities, _ = _convert(tmp_path)
    first, second = _by_type(entities, "QPC.digitelQpc")
    assert "name" not in first
    assert first["unit"] == "0A"
    assert "unit" not in second


def test_qpc_ion_pump_takes_its_controllers_port_and_unit(tmp_path: Path):
    entities, warnings = _convert(tmp_path)
    first, second, orphan = _by_type(entities, "QPC.digitelQpcIonp")
    # the controller comes after the pump in the XML
    assert first["port"] == "MPC_A_04_PORT"
    assert first["unit"] == "0A"
    assert first["spon"] == "1.0E-10"
    assert first["spoff"] == "1.0E-4"
    for pump in (first, second, orphan):
        assert "QPC" not in pump
        assert "name" not in pump
        assert "alh" not in pump
    assert second["port"] == "MPC_A_04_PORT"
    assert "unit" not in second
    assert second["spon"] == "1e-9"
    assert "port" not in orphan
    assert any("SR99A-VA-IONP-09 names no digitelQpc" in w for w in warnings)


def test_ether_ip_ao(tmp_path: Path):
    entities, warnings = _convert(tmp_path)
    setpoint, reset = _by_type(entities, "ether_ip.ao")
    assert setpoint == {
        "type": "ether_ip.ao",
        "record": "SR99C-VA-VLVCC-01:GB:IDX_SP",
        "port": "VLVCC_01_EIP",
        "tag": "GB_Index_Setpoint S 0.5",
        "scan": "Passive",
    }
    assert reset["tag"] == "CAVITY_RESET_01 S .2"
    assert reset["scan"] == "Passive"

    dropped = [w for w in warnings if "became ether_ip.ao" in w]
    assert len(dropped) == 2
    assert "SR99C-VA-VLVCC-01:GB:IDX_SP" in dropped[0]
    assert "DRVH=3000, DRVL=0, PREC=2" in dropped[0]
    assert "PRIO=HIGH, VAL=1" in dropped[1]


def test_other_raw_records_still_dropped(tmp_path: Path):
    entities, warnings = _convert(tmp_path)
    assert not [e for e in entities if e["type"].startswith("records.")]
    assert any(
        w.startswith(f"{IOC}: won't convert 2 records.ao entities") for w in warnings
    )
    assert any(
        w.startswith(f"{IOC}: won't convert 1 records.bo entity") for w in warnings
    )
