"""
Tests for the positioner converter's motorpositioner handling.

motorpositioner.template links to its motor as $(P)$(motor), with P taken
from the parent multipositioner, so the converter must set motor to the motor
record's suffix and refuse a motor whose prefix differs (issue #103). As in
XMLbuilder, the motor is found by name whatever its type.
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


def test_any_motor_type_is_found_by_name(tmp_path: Path):
    # XMLbuilder accepted any MotorRecord: here a coordinate system motor and
    # an auto_* soft motor whose template makes the record $(P)$(M)
    mps = _motorpositioners(
        tmp_path,
        """
  <pmac.dls_pmac_cs_asyn_motor ADDR="9" DESC="CS Y" EGU="mm" M=":CS:Y"
    MRES="0.0001" P="BL01C-MO-STAGE-01" PORT="BRICK1.CS2" PREC="5"
    name="STAGE.CSY"/>
  <BL24B.auto_pgmAutoDecouple DECOUPLING_DISTANCE="1" DESC="soft" EGU="deg"
    M=":SOFT" P="BL01C-MO-STAGE-01" REAL_MOTOR="REAL" name="STAGE.SOFT"/>
  <positioner.multipositioner DESC="stage" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="STAGE.MP"/>
  <positioner.motorpositioner DESC="cs" MP="STAGE.MP" PREC="3" Q=":CS:P"
    VALB="1" motor="STAGE.CSY" name="STAGE.CSP"/>
  <positioner.motorpositioner DESC="soft" MP="STAGE.MP" PREC="3" Q=":SOFT:P"
    VALB="1" motor="STAGE.SOFT" name="STAGE.SOFTP"/>
""",
    )

    assert [(m["motor"], m["EGU"]) for m in mps] == [
        (":CS:Y", "mm"),
        (":SOFT", "deg"),
    ]


def test_motor_without_m_or_q_names_its_type(tmp_path: Path):
    with pytest.raises(ValueError, match="of type 'positioner.multipositioner'"):
        _motorpositioners(
            tmp_path,
            """
  <positioner.multipositioner DESC="stage" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="STAGE.MP"/>
  <positioner.motorpositioner DESC="y" MP="STAGE.MP" PREC="3" Q=":Y:P"
    VALB="1" motor="STAGE.MP" name="STAGE.YP"/>
""",
        )


def test_missing_motor_names_the_motorpositioner(tmp_path: Path):
    with pytest.raises(ValueError, match="motorpositioner 'STAGE.YP', found 0"):
        _motorpositioners(
            tmp_path,
            """
  <positioner.multipositioner DESC="stage" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="STAGE.MP"/>
  <positioner.motorpositioner DESC="y" MP="STAGE.MP" PREC="3" Q=":Y:P"
    VALB="1" motor="NOSUCH" name="STAGE.YP"/>
""",
        )
