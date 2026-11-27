"""
The granvillePhillips and BL05I converters, checked on the converted entities
alone, before any runtime pattern is consulted: both patterns' models are newer
than the releases the tests pin.
"""

from typing import Any

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch

GRANVILLE_XML = """\
<components arch="linux-x86_64">
  <granvillePhillips.gp350 gctrl="BL06K-VA-GCTLR-03" name="GCTLR03" port="p03"/>
  <granvillePhillips.gp307 gctrl="BL05I-VA-GCTLR-11" name="GCTLR11" port="p11"/>
  <granvillePhillips.gp350Gauge dom="BL06K" gctrl="BL06K-VA-GCTLR-03" id="03"
    name="GCTLR-03"/>
  <granvillePhillips.gp350Hcg GCTLR="GCTLR03" device="BL06K-VA-HCG-02"
    gctrl="BL06K-VA-GCTLR-03" name="HCG-02"/>
  <granvillePhillips.gp307Pirg GCTLR="GCTLR11" channel="1"
    device="BL05I-VA-GPIRG-04" gctrl="BL05I-VA-GCTLR-11" name="GPIRG4"/>
</components>
"""

BL05I_XML = """\
<components arch="linux-x86_64">
  <pmac.GeoBrick ControlIP="ts" ControlMode="ts" ControlPort="7018"
    MovingPoll="50" P="BL05I-MO-STEP-02" Port="BRICK02_Port" name="BRICK02"/>
  <pmac.GeoBrick ControlIP="ts" ControlMode="ts" ControlPort="7020"
    MovingPoll="50" P="BL05I-MO-STEP-04" Port="BRICK04_Port" name="BRICK04"/>
  <pmac.GeoBrick ControlIP="ts" ControlMode="ts" ControlPort="7022"
    IdlePoll="1000" P="BL05I-MO-STEP-06" Port="BRICK06_Port" name="BRICK06"/>
  <BL05I.BL05I_changeHexapodMirror_withRef M1NAME="MJ6" M2NAME="M3"
    P="BL05I-OP-SWTCH-01" PLC="12" PORT="BRICK04_Port" R=":MIRCTRL"
    YMTR="BL05I-OP-SWTCH-01:Y" name="M3MJ6.CHANGE"/>
  <BL05I.BL05I_changeHexapodMirror P="BL05I-OP-RFM-01" PLC="11"
    PORT="BRICK06_Port" R=":MIRCTRL" YMTR="BL05I-OP-RFM-01:Y" name="M4M5"/>
  <asyn.AsynIP name="vts_H2OPLC1" port="10.0.0.1:7005"/>
  <BL05I.BL05I_waterchiller P="BL05I-HO-CHILL-01" PLCNAME="BL05I-HO-PLC-01"
    name="HO1.M1_Chiller" port="vts_H2OPLC1"/>
  <BL05I.BL05I_waterchiller P="BL05I-HO-CHILL-02" PLCNAME="BL05I-HO-PLC-02"
    name="HO1.PGM_Chiller" port="vts_H2OPLC1"/>
</components>
"""


def _entities(xml: str) -> list[dict[str, Any]]:
    builder = Builder()
    builder.load_string(xml)
    return [dict(e) for e in dispatch(builder, "test.xml").entities]


def _of_type(entities: list[dict[str, Any]], entity_type: str) -> list[dict]:
    return [e for e in entities if e["type"] == entity_type]


def test_granville_controllers_keep_their_name_and_gauges_drop_it():
    entities = _entities(GRANVILLE_XML)

    assert _of_type(entities, "granvillePhillips.gp350")[0]["name"] == "GCTLR03"
    assert _of_type(entities, "granvillePhillips.gp307")[0]["name"] == "GCTLR11"
    for leaf in ("gp350Gauge", "gp350Hcg", "gp307Pirg"):
        assert "name" not in _of_type(entities, f"granvillePhillips.{leaf}")[0]
    assert _of_type(entities, "granvillePhillips.gp350Hcg")[0]["GCTLR"] == "GCTLR03"


def test_granville_gauge_readback_drops_gctrl():
    entities = _entities(GRANVILLE_XML)

    gauge = _of_type(entities, "granvillePhillips.gp350Gauge")[0]
    assert "gctrl" not in gauge
    assert gauge["dom"] == "BL06K"


def test_hexapod_port_becomes_the_geobrick_it_names():
    entities = _entities(BL05I_XML)

    with_ref = _of_type(entities, "BL05I.BL05I_changeHexapodMirror_withRef")[0]
    plain = _of_type(entities, "BL05I.BL05I_changeHexapodMirror")[0]
    assert with_ref["PmacController"] == "BRICK04"
    assert plain["PmacController"] == "BRICK06"
    for hexapod in (with_ref, plain):
        assert "PORT" not in hexapod
        assert "name" not in hexapod


def test_hexapod_bricks_poll_at_200ms_unless_the_xml_says():
    bricks = {e["name"]: e for e in _of_type(_entities(BL05I_XML), "pmac.GeoBrick")}

    # no hexapod switch on BRICK02
    assert "IdlePoll" not in bricks["BRICK02"]
    assert bricks["BRICK04"]["IdlePoll"] == 200
    assert bricks["BRICK06"]["IdlePoll"] == 1000
    # the key order do_dispatch gives every entity: type, then the rest sorted
    keys = list(bricks["BRICK04"])
    assert keys[0] == "type" and keys[1:] == sorted(keys[1:])


def test_water_chillers_pull_in_hostlink_once():
    entities = _entities(BL05I_XML)
    types = [e["type"] for e in entities]

    assert types.count("HostLink.HostLink") == 1
    assert types.index("HostLink.HostLink") < types.index("BL05I.BL05I_waterchiller")
    for chiller in _of_type(entities, "BL05I.BL05I_waterchiller"):
        assert "name" not in chiller
