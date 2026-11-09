"""
Tests for the interlock and BLGui converters.

interlock.interlock addr is a 10-word block number (block nn = DM nn*10);
dlsPLC.interlock addr is the first DM address, and the interlock needs a
dlsPLC.read100 for century addr//100 on its device.

BLGui auto_BLGui_status / auto_BLGui_device map to BLGui.status / BLGui.device.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file
from tests.conftest import requires_support

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <FINS.FINSHostlink asyn_port="ty_40_0" name="VLVCC1.Hostlink"/>
  <FINS.FINSHostlink asyn_port="ty_40_1" name="TMPCC1.Hostlink"/>
  <dlsPLC.read100 century="0" device="BL01C-VA-VLVCC-01" name="VLVCC1.0"
    port="VLVCC1.Hostlink"/>
  <!-- block 07 = DM70: century 0, read100 already present -->
  <interlock.interlock addr="07" desc="Water" device="BL01C-VA-VLVCC-01"
    ilk0="Flow" interlock=":INT1" name="ILK1" port="VLVCC1.Hostlink"/>
  <!-- block 39 = DM390: century 3, no read100 anywhere -->
  <interlock.interlock addr="39" desc="Beam" device="BL01C-VA-VLVCC-01"
    ilk0="V1" interlock=":INT2" name="ILK2" port="VLVCC1.Hostlink"/>
  <!-- a second interlock in century 3 must not add another read100 -->
  <interlock.interlock addr="38" desc="Beam2" device="BL01C-VA-VLVCC-01"
    ilk0="V2" interlock=":INT3" name="ILK3" port="VLVCC1.Hostlink"/>
  <!-- block 01 = DM10 on the TMPCC: its read100 comes later in the XML -->
  <interlock.interlock addr="01" desc="Temps" device="BL01C-VA-TMPCC-01"
    ilk0="T1" interlock=":INT1" name="ILK4" port="TMPCC1.Hostlink"/>
  <dlsPLC.read100 century="0" device="BL01C-VA-TMPCC-01" name="TMPCC1.0"
    port="TMPCC1.Hostlink"/>
  <BLGui.auto_BLGui_status CALC="0" INPA="BL01C-RS-GBC-01:FLOWSTA MS"
    INPB="0" INPC="0" INPD="0" INPE="0" INPF="0" INPG="0" INPH="0" INPI="0"
    INPJ="0" INPK="0" INPL="0" P="BL01C-RS-GBC-01:DEVSTA" PHAS="2"
    name=".OB1"/>
  <BLGui.auto_BLGui_device BL_ORDER="3" BL_SECTION="ALL" DESCRIPTION="Gate"
    GDA_DESC="Gate Valve" GDA_NAME="GV1" MTYPE="0" NCURR="0" NFLOW="1"
    NTEMP="2" P="BL01C-VA-VALVE-01" SHORTNAME="1" name=".OB2"/>
  <!-- older BLGui XMLs omit BL_SECTION and BL_ORDER -->
  <BLGui.auto_BLGui_device DESCRIPTION="Periscope" MTYPE="0" NCURR="0"
    NFLOW="0" NTEMP="0" P="BL01C-OP-PERI-01" SHORTNAME="P1"/>
</components>
"""


def _convert(tmp_path: Path) -> list[dict]:
    xml = tmp_path / "ioc.xml"
    xml.write_text(XML)
    yaml = tmp_path / "ioc.yaml"
    convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")
    return YAML(typ="safe").load(yaml.read_text())["entities"]


@requires_support
def test_interlock_addr_is_block_times_ten(tmp_path: Path):
    entities = _convert(tmp_path)
    addrs = {
        e["interlock"] + "@" + e["device"]: e["addr"]
        for e in entities
        if e["type"] == "dlsPLC.interlock"
    }
    assert addrs == {
        ":INT1@BL01C-VA-VLVCC-01": 70,
        ":INT2@BL01C-VA-VLVCC-01": 390,
        ":INT3@BL01C-VA-VLVCC-01": 380,
        ":INT1@BL01C-VA-TMPCC-01": 10,
    }


@requires_support
def test_interlock_adds_missing_read100_once(tmp_path: Path):
    entities = _convert(tmp_path)
    read100s = [
        (e["device"], e["century"], e["port"])
        for e in entities
        if e["type"] == "dlsPLC.read100"
    ]
    assert sorted(read100s) == [
        ("BL01C-VA-TMPCC-01", 0, "TMPCC1.Hostlink"),
        ("BL01C-VA-VLVCC-01", 0, "VLVCC1.Hostlink"),
        ("BL01C-VA-VLVCC-01", 3, "VLVCC1.Hostlink"),
    ]

    # the added read100 sits just before the first interlock that needs it
    types = [(e["type"], e.get("century", e.get("addr"))) for e in entities]
    i = types.index(("dlsPLC.read100", 3))
    assert types[i + 1] == ("dlsPLC.interlock", 390)


@requires_support
def test_blgui_status_and_device(tmp_path: Path):
    entities = _convert(tmp_path)
    blgui = [e for e in entities if e["type"].startswith("BLGui.")]
    assert blgui == [
        {
            "type": "BLGui.status",
            "CALC": "0",
            "INPA": "BL01C-RS-GBC-01:FLOWSTA MS",
            "P": "BL01C-RS-GBC-01:DEVSTA",
            "PHAS": 2,
        },
        {
            "type": "BLGui.device",
            "BL_ORDER": 3,
            "BL_SECTION": "ALL",
            "DESCRIPTION": "Gate",
            "GDA_DESC": "Gate Valve",
            "GDA_NAME": "GV1",
            "NFLOW": 1,
            "NTEMP": 2,
            "P": "BL01C-VA-VALVE-01",
            "SHORTNAME": "1",
        },
        {
            "type": "BLGui.device",
            "BL_ORDER": 0,
            "BL_SECTION": "",
            "DESCRIPTION": "Periscope",
            "P": "BL01C-OP-PERI-01",
            "SHORTNAME": "P1",
        },
    ]
