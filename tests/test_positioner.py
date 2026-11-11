"""
Tests for the positioner converter.

motorpositioner.template links to its motor as $(P)$(motor), with P taken
from the parent multipositioner, so the converter must set motor to the motor
record's suffix and refuse a motor whose prefix differs (issue #103). As in
XMLbuilder, the motor is found by name whatever its type, and positioners
take their multipositioner's slots A, B, C ... in XML order.
"""

import subprocess
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


def _convert(tmp_path: Path, body: str) -> list[dict]:
    xml = tmp_path / "ioc.xml"
    xml.write_text(HEADER + body + "</components>\n")
    yaml = tmp_path / "ioc.yaml"
    convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")
    ioc = YAML(typ="safe").load(yaml.read_text())
    return [e for e in ioc["entities"] if e["type"].startswith("positioner.")]


def _motorpositioners(tmp_path: Path, body: str) -> list[dict]:
    return [
        e for e in _convert(tmp_path, body) if e["type"] == "positioner.motorpositioner"
    ]


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


def test_positioners_take_slots_in_xml_order(tmp_path: Path):
    # as XMLbuilder's multipositioner.addPositioner: positioners and
    # motorpositioners share one sequence of slots per multipositioner
    entities = _convert(
        tmp_path,
        """
  <positioner.multipositioner DESC="one" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="ONE"/>
  <positioner.multipositioner DESC="two" MP=":MP2" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="TWO"/>
  <positioner.motorpositioner DESC="y" MP="ONE" PREC="3" Q=":Y:P"
    motor="STAGE.Y"/>
  <positioner.positioner DEADBAND="0.1" DESC="pv" MP="ONE" Q=":PV:P"
    READBACK="RBV" SET="SET" STOP="STOP"/>
  <positioner.motorpositioner DESC="pz" MP="TWO" PREC="3" Q=":PZ:P"
    motor="STAGE.PZ"/>
  <positioner.motorpositioner DESC="pz" MP="ONE" PREC="3" Q=":PZ:P1"
    motor="STAGE.PZ"/>
""",
    )

    # pos A is the model's default, so it is left out of the YAML
    assert [(e["Q"], e.get("pos", "A")) for e in entities if "Q" in e] == [
        (":Y:P", "A"),
        (":PV:P", "B"),
        (":PZ:P", "A"),
        (":PZ:P1", "C"),
    ]


def test_explicit_pos_is_kept(tmp_path: Path):
    entities = _convert(
        tmp_path,
        """
  <positioner.multipositioner DESC="one" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="ONE"/>
  <positioner.motorpositioner DESC="y" MP="ONE" PREC="3" Q=":Y:P"
    motor="STAGE.Y" pos="B"/>
  <positioner.motorpositioner DESC="pz" MP="ONE" PREC="3" Q=":PZ:P"
    motor="STAGE.PZ"/>
  <positioner.motorpositioner DESC="pz" MP="ONE" PREC="3" Q=":PZ:P1"
    motor="STAGE.PZ"/>
""",
    )

    # later positioners skip the slot the XML gives
    assert [e.get("pos", "A") for e in entities if "Q" in e] == ["B", "A", "C"]


def test_more_than_eight_positioners_is_an_error(tmp_path: Path):
    positioners = "".join(
        f"""
  <positioner.motorpositioner DESC="y" MP="ONE" PREC="3" Q=":Y:P{i}"
    motor="STAGE.Y"/>"""
        for i in range(9)
    )
    with pytest.raises(ValueError, match="'ONE' has more than 8 positioners"):
        _convert(
            tmp_path,
            """
  <positioner.multipositioner DESC="one" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="ONE"/>
"""
            + positioners
            + "\n",
        )


def test_multipositioner_drops_gui_macros(tmp_path: Path):
    # NPOS and P1..P8 are screen macros XMLbuilder computes itself
    entities = _convert(
        tmp_path,
        """
  <positioner.multipositioner DESC="one" MP=":MP" NPOS="2" P="BL01C-MO-STAGE-01"
    P1="P1" P2="P2" P1_VALS="Y" STRA="Out" STRB="In" name="ONE"/>
  <positioner.motorpositioner DESC="y" MP="ONE" PREC="3" Q=":Y:P"
    motor="STAGE.Y"/>
""",
    )

    mp = entities[0]
    assert "NPOS" not in mp and "P1" not in mp and "P2" not in mp
    assert mp["P1_VALS"] == "Y"


def test_external_motor_drops_name(tmp_path: Path):
    entities = _convert(
        tmp_path,
        """
  <positioner.motorpositioner_external_motor DESC="light" EGU="%" MP=":MP"
    P="BL01C-EA-OAV-01:FZOOM" PREC="1" Q=":PI" VALB="10" motor=":I"
    name="BLIT" pos="B"/>
""",
    )

    assert entities == [
        {
            "type": "positioner.motorpositioner_external_motor",
            "DESC": "light",
            "EGU": "%",
            "MP": ":MP",
            "P": "BL01C-EA-OAV-01:FZOOM",
            "PREC": 1,
            "Q": ":PI",
            "VALB": 10,
            "motor": ":I",
            "pos": "B",
        }
    ]


def test_external_motor_generates(tmp_path: Path, ibek_defs):
    # the converted entity validates against the positioner entity model and
    # loads motorpositioner.template with the prefix and motor it was given;
    # no HEADER, whose motors are not complete enough to generate
    xml = tmp_path / "ioc.xml"
    xml.write_text(
        """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <positioner.multipositioner DESC="light" MP=":MP" P="BL01C-EA-OAV-01:FZOOM"
    STRA="Off" STRB="On" name="ONE"/>
  <positioner.motorpositioner_external_motor DESC="light" EGU="%" MP=":MP"
    P="BL01C-EA-OAV-01:FZOOM" PREC="1" Q=":PI" VALB="10" motor=":I"
    name="BLIT" pos="B"/>
</components>
"""
    )
    convert_file(xml, tmp_path / "ioc.yaml", "/epics/ibek-defs/ioc.schema.json")
    result = subprocess.run(
        ["ibek", "runtime", "generate2", str(tmp_path), "--output", str(tmp_path)]
        + ["--no-pvi"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    subst = (tmp_path / "ioc.subst").read_text()
    row = next(line for line in subst.splitlines() if ":PI" in line)
    assert '"BL01C-EA-OAV-01:FZOOM"' in row
    assert '":I"' in row


def test_empty_m_gives_an_empty_motor_suffix(tmp_path: Path):
    # a motor whose record is $(P) alone, as on the LI SLED
    entities = _convert(
        tmp_path,
        """
  <motor.basic_asyn_motor ADDR="0" DESC="sled" EGU="mm" M="" MRES="0.001"
    P="BL01C-MO-SLED-01" PORT="SLED" PREC="3" name="SLED.M"/>
  <positioner.multipositioner DESC="sled" MP=":MP" P="BL01C-MO-SLED-01"
    STRA="Out" STRB="In" name="SLED.MP"/>
  <positioner.motorpositioner DESC="sled" MP="SLED.MP" PREC="3" Q=":P"
    motor="SLED.M"/>
""",
    )

    assert [e["motor"] for e in entities if "Q" in e] == [""]


def test_unnamed_motorpositioner_is_reported_by_q(tmp_path: Path):
    with pytest.raises(ValueError, match="motorpositioner ':Y:P', found 0"):
        _convert(
            tmp_path,
            """
  <positioner.multipositioner DESC="stage" MP=":MP" P="BL01C-MO-STAGE-01"
    STRA="Out" STRB="In" name="STAGE.MP"/>
  <positioner.motorpositioner DESC="y" MP="STAGE.MP" PREC="3" Q=":Y:P"
    motor="NOSUCH"/>
""",
        )
