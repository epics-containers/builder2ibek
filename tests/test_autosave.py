from pathlib import Path

from builder2ibek.db2autosave import parse_templates, write_req_file

MOTOR = Path(__file__).parent / "samples" / "motor.template"


def test_autosave(tmp_path: Path):
    output = tmp_path / "autosave"
    output.mkdir()

    parse_templates(output, [MOTOR])

    positions = (output / "motor_positions.req").read_text().splitlines()
    settings = (output / "motor_settings.req").read_text().splitlines()

    # "#% autosave 0 DVAL OFF" -> one line per field
    assert positions == ["$(P)$(M).DVAL", "$(P)$(M).OFF"]

    # "#% autosave 1 DIR DHLM ... MDEL" -> one line per field
    assert "$(P)$(M).DIR" in settings
    assert "$(P)$(M).MDEL" in settings

    # "#% autosave 1 VAL" -> the bare record name
    assert "$(P)$(M):FERRORMAX" in settings
    assert "$(P)$(M):FERRORMAX.VAL" not in settings


def test_autosave_one_pv_per_line(tmp_path: Path):
    """
    autosave's readReqFile() reads only the first whitespace-delimited token of
    a line and silently drops the rest, so a req line must hold exactly one PV.
    """
    output = tmp_path / "autosave"
    output.mkdir()

    parse_templates(output, [MOTOR])

    req_files = sorted(output.glob("*.req"))
    assert req_files, "no req files written"
    for req_file in req_files:
        text = req_file.read_text()
        assert text.endswith("\n"), f"{req_file.name} has no trailing newline"
        for line in text.splitlines():
            assert len(line.split()) == 1, f"{req_file.name}: multi-PV line {line!r}"


def test_autosave_empty_expansion_writes_nothing(tmp_path: Path):
    """
    A record_set that expands to no PVs must not leave a req file behind.

    Joining an empty set and appending the terminator writes a single blank
    line, i.e. a line naming no PV -- which breaks the invariant asserted by
    test_autosave_one_pv_per_line above.
    """
    req_file = tmp_path / "empty_settings.req"

    write_req_file(req_file, {"", "   "})

    assert not req_file.exists()
