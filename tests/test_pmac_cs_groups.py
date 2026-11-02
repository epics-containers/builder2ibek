"""
Tests for the pmac converter's coordinate system group finalizer.

pmacCreateCsGroup names a group, but the COORDINATE_SYS_GROUP mbbo takes its
state strings from the controller's CSG0..CSG7 template arguments, so the
converter has to copy each group's name onto its controller (issue #143).
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file
from tests.conftest import requires_support

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <!-- group declared BEFORE its controller -->
  <pmac.pmacCreateCsGroup AxisCount="3" Controller="PPMAC1"
    GroupName="StraightThrough" GroupNumber="1" name="PPMAC1.ST"/>
  <pmac.pmacAsynSSHPort IP="10.0.0.1" PASSWORD="x" name="PPMAC1port"/>
  <pmac.PowerPMAC P="BL01C-MO-PPMAC-01" Port="PPMAC1port" name="PPMAC1"/>
  <!-- a second group on the same controller, at the top of the range -->
  <pmac.pmacCreateCsGroup AxisCount="2" Controller="PPMAC1"
    GroupName="Top" GroupNumber="7" name="PPMAC1.TOP"/>

  <!-- controller declared BEFORE its groups, already naming CSG3 -->
  <pmac.pmacAsynIPPort IP="10.0.0.2" name="BRICK1port"/>
  <pmac.GeoBrick P="BL01C-MO-STEP-01" Port="BRICK1port" name="BRICK1"
    CSG3="Preset"/>
  <pmac.pmacCreateCsGroup AxisCount="9" Controller="BRICK1"
    GroupName="Default" GroupNumber="0" name="BRICK1.DEFAULT"/>
  <pmac.pmacCreateCsGroup AxisCount="9" Controller="BRICK1"
    GroupName="Clash" GroupNumber="3" name="BRICK1.CLASH"/>
  <!-- pmacController.template has no column for this one -->
  <pmac.pmacCreateCsGroup AxisCount="1" Controller="BRICK1"
    GroupName="TooHigh" GroupNumber="9" name="BRICK1.NINE"/>
</components>
"""


def _convert(tmp_path: Path) -> dict[str, dict]:
    """Convert XML and return the controller entities keyed by name."""
    xml = tmp_path / "ioc.xml"
    xml.write_text(XML)
    yaml = tmp_path / "ioc.yaml"
    convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")

    ioc = YAML(typ="safe").load(yaml.read_text())
    return {
        e["name"]: e
        for e in ioc["entities"]
        if e["type"] in ("pmac.PowerPMAC", "pmac.GeoBrick")
    }


@requires_support
def test_cs_group_names_reach_the_controller(tmp_path: Path, capsys):
    controllers = _convert(tmp_path)
    ppmac = controllers["PPMAC1"]
    brick = controllers["BRICK1"]

    # the name lands on CSG<GroupNumber> whichever side of the group the
    # controller is declared, and several groups can share a controller
    assert ppmac["CSG1"] == "StraightThrough"
    assert ppmac["CSG7"] == "Top"
    assert brick["CSG0"] == "Default"

    # a CSGn the controller already carries is not overwritten
    assert brick["CSG3"] == "Preset"

    # nothing else was invented
    assert sorted(k for k in ppmac if k.startswith("CSG")) == ["CSG1", "CSG7"]
    assert sorted(k for k in brick if k.startswith("CSG")) == ["CSG0", "CSG3"]

    # the group above 7 warns and is left off rather than emitting CSG9
    out = capsys.readouterr().out
    assert "TooHigh" in out and "GroupNumber 9" in out


@requires_support
def test_cs_group_keys_keep_sorted_order(tmp_path: Path):
    """
    finalize runs after do_dispatch has sorted each entity's keys, so a
    controller it adds a CSGn to must be put back into that order: type
    first, then the rest sorted.
    """
    controllers = _convert(tmp_path)

    for entity in controllers.values():
        keys = list(entity)
        assert keys[0] == "type"
        assert keys[1:] == sorted(keys[1:])
