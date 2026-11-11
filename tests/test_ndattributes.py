"""
Tests for the ADCore.NDAttributes conversion.

XMLbuilder wrote one NDAttributes XML file per port from the ADCore.NDAttributes
elements that name it, and set the port's NDAttributesFile to it. builder2ibek
puts that XML inline in the ATTRIBUTES_FILE of the port's driver or plugin, or,
where the entity model has no ATTRIBUTES_FILE, in a file next to the ioc.yaml
set by an ADCore.NDAttributesConfig entity. The samples ndattributes.xml and
BL18B-EA-IOC-24.xml cover both through generate2.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file
from builder2ibek.converters.ADCore import attributes_xml, nd_attribute
from tests.conftest import requires_support

SAMPLES = Path(__file__).parent / "samples"

HEADER = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <ADCore.NDStats NDARRAY_PORT="DET1.cam" P="BL99P-EA-DET-01" PORT="DET1.stat"
    R=":STAT:"/>
"""


def _convert(tmp_path: Path, body: str):
    xml = tmp_path / "ioc.xml"
    xml.write_text(HEADER + body + "</components>\n")
    yaml = tmp_path / "ioc.yaml"
    result = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")
    ioc = YAML(typ="safe").load(yaml.read_text())
    return ioc["entities"], result.warnings


def test_epics_pv_defaults():
    # as builder.py: type EPICS_PV, dbrtype DBR_NATIVE, and a name made from
    # the port and the source
    assert nd_attribute({"port": "DET1.cam", "source": "SR-DI-DCCT-01:SIGNAL"}) == {
        "name": "DET1.cam.SR-DI-DCCT-01:SIGNAL",
        "type": "EPICS_PV",
        "source": "SR-DI-DCCT-01:SIGNAL",
        "description": "",
        "dbrtype": "DBR_NATIVE",
    }


def test_param_defaults():
    assert nd_attribute(
        {"port": "DET1.cam", "source": "ARRAY_COUNTER", "type": "PARAM"}
    ) == {
        "name": "DET1.cam.ARRAY_COUNTER",
        "type": "PARAM",
        "source": "ARRAY_COUNTER",
        "description": "",
        "datatype": "INT",
        "addr": "0",
    }


def test_xml_escapes_values():
    xml = attributes_xml(
        [{"name": "A", "description": "a & \"b\" <c> 'd'", "source": "S"}]
    )
    assert xml == (
        "<Attributes>\n"
        "  <Attribute description=\"a &amp; &quot;b&quot; &lt;c&gt; 'd'\" "
        'name="A" source="S"/>\n'
        "</Attributes>\n"
    )


@requires_support
def test_inline_on_plugin(tmp_path: Path):
    entities, warnings = _convert(
        tmp_path,
        """
  <ADCore.NDAttributes attrname="Drop" description="dropped" port="DET1.stat"
    source="DROPPED_ARRAYS" type="PARAM"/>
  <ADCore.NDAttributes port="DET1.stat" source="BL99P-EA-DET-01:CAM:Temp"/>
""",
    )

    assert warnings == []
    assert not [e for e in entities if e["type"] == "ADCore.NDAttributes"]
    (stats,) = [e for e in entities if e["type"] == "ADCore.NDStats"]
    assert stats["ATTRIBUTES_FILE"] == (
        "<Attributes>\n"
        '  <Attribute addr="0" datatype="INT" description="dropped" name="Drop" '
        'source="DROPPED_ARRAYS" type="PARAM"/>\n'
        '  <Attribute dbrtype="DBR_NATIVE" description="" '
        'name="DET1.stat.BL99P-EA-DET-01:CAM:Temp" '
        'source="BL99P-EA-DET-01:CAM:Temp" type="EPICS_PV"/>\n'
        "</Attributes>\n"
    )
    # keys stay in the order do_dispatch gives them
    keys = list(stats)
    assert keys[0] == "type" and keys[1:] == sorted(keys[1:])


@requires_support
def test_unknown_port_is_dropped_with_a_warning(tmp_path: Path):
    entities, warnings = _convert(
        tmp_path,
        """
  <ADCore.NDAttributes port="NOWHERE" source="X"/>
""",
    )

    assert not [e for e in entities if "ATTRIBUTES_FILE" in e]
    assert len(warnings) == 1
    assert "dropped 1 ADCore.NDAttributes for port NOWHERE" in warnings[0]


@requires_support
def test_model_without_attributes_file_gets_a_config_file(tmp_path: Path):
    # ADPilatus.pilatusDetector has no ATTRIBUTES_FILE: the XML goes in a
    # file next to the ioc.yaml, which an ADCore.NDAttributesConfig sets
    sample = SAMPLES / "BL18B-EA-IOC-24.xml"
    yaml = tmp_path / "ioc.yaml"
    result = convert_file(sample, yaml, "/epics/ibek-defs/ioc.schema.json")

    side_file = tmp_path / "PILATUS.cam.xml"
    assert (
        side_file.read_text()
        == (SAMPLES / "config" / "bl18b-ea-ioc-24" / "PILATUS.cam.xml").read_text()
    )
    assert any("PILATUS.cam.xml" in w for w in result.warnings)

    entities = YAML(typ="safe").load(yaml.read_text())["entities"]
    types = [e["type"] for e in entities]
    config = entities[types.index("ADPilatus.pilatusDetector") + 1]
    assert config == {
        "type": "ADCore.NDAttributesConfig",
        "P": "BL18B-EA-PILAT-01",
        "R": ":CAM:",
        "ATTRIBUTES_FILE": "PILATUS.cam.xml",
    }
