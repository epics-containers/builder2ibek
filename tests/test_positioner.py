"""
Tests for the positioner converter's motorpositioner handling.

motorpositioner.template links to its motor as $(P)$(motor), with P taken
from the parent multipositioner, so the converter must set motor to the motor
record's suffix and refuse a motor whose prefix differs (issue #103).
"""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

HEADER = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <pmac.dls_pmac_asyn_motor ADDR="1" DESC="Y" EGU="mm" M=":Y" MRES="0.001"
    P="BL01C-MO-STAGE-01" PORT="BRICK1" PREC="3" SPORT="BRICK1port"
    name="STAGE.Y"/>
  <motor.softMotorForPiezo P="BL01C-MO-STAGE-01" Q=":PZ" DESC="piezo"
    EGU="um" name="STAGE.PZ"/>
"""


def _motorpositioners(tmp_path: Path, body: str) -> list[dict]:
    xml = tmp_path / "ioc.xml"
    xml.write_text(HEADER + body + "</components>\n")
    yaml = tmp_path / "ioc.yaml"
    convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")

    ioc = YAML(typ="safe").load(yaml.read_text())
    return [e for e in ioc["entities"] if e["type"] == "positioner.motorpositioner"]


def test_motor_is_the_suffix_not_the_pv(tmp_path: Path):
    mps = _motorpositioners(
        tmp_path,
        """
  <positioner.multipositioner DESC="stage" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="STAGE.MP"/>
  <positioner.motorpositioner DESC="y" MP="STAGE.MP" PREC="3" Q=":Y:P"
    VALB="1" motor="STAGE.Y" name="STAGE.YP"/>
  <positioner.motorpositioner DESC="pz" MP="STAGE.MP" PREC="3" Q=":PZ:P"
    VALB="1" motor="STAGE.PZ" name="STAGE.PZP"/>
""",
    )

    # pmac and basic motors use M, softMotorForPiezo uses Q
    assert [(m["motor"], m["EGU"]) for m in mps] == [(":Y", "mm"), (":PZ", "um")]


def test_motor_prefix_must_match_the_multipositioner(tmp_path: Path):
    with pytest.raises(ValueError, match="does not match multipositioner"):
        _motorpositioners(
            tmp_path,
            """
  <positioner.multipositioner DESC="other" MP=":MP" P="BL01C-MO-OTHER-01"
    STRA="Out" STRB="In" name="OTHER.MP"/>
  <positioner.motorpositioner DESC="y" MP="OTHER.MP" PREC="3" Q=":Y:P"
    VALB="1" motor="STAGE.Y" name="OTHER.YP"/>
""",
        )
