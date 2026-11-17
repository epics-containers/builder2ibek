"""Beamline modules come only from their ibek-runtime-support pattern.

An entity of a beamline module that the module's pattern does not take is left
out of the ioc.yaml, with a warning and a comment listing it for manual review.
"""

import re
from pathlib import Path

import pytest
from ibek.pattern_cmds.schema import SCHEMA_HEADER, rewrite_ioc_yaml_header
from ruamel.yaml import YAML
from typer.testing import CliRunner

from builder2ibek import convert, patterns, vendor_patterns
from builder2ibek.__main__ import cli
from builder2ibek.builder import Builder
from builder2ibek.convert import convert_file, dispatch
from builder2ibek.patterns import (
    SUPPORT_LIBRARY,
    BeamlinePatternError,
    PatternIndex,
    PatternIndexError,
    drop_beamline_entities,
    pattern_index,
)
from tests.pattern_pins import SUPPORT_PATTERN_LIBRARY, SUPPORT_PATTERN_TAG

BL21I = f"{SUPPORT_LIBRARY}:BL21I@{SUPPORT_PATTERN_TAG}"

# Every record type the ioc-streamdevice-runtime image provides: EPICS base,
# calc (with sseq and transform, from calcSupport_LOCAL.dbd), busy, std and
# asyn. stream adds device support, not record types.
BASE_RECORDS = {
    "aai", "aao", "ai", "ao", "aSub", "bi", "bo", "calc", "calcout", "compress",
    "dfanout", "event", "fanout", "histogram", "int64in", "int64out", "longin",
    "longout", "lsi", "lso", "mbbi", "mbbiDirect", "mbbo", "mbboDirect",
    "permissive", "printf", "sel", "seq", "state", "stringin", "stringout",
    "sub", "subArray", "waveform",
}  # fmt: skip
CALC_RECORDS = {"scalcout", "acalcout", "sseq", "transform", "swait"}
STD_RECORDS = {"epid", "throttle", "timestamp"}
RUNTIME_IMAGE_RECORDS = BASE_RECORDS | CALC_RECORDS | STD_RECORDS | {"busy", "asyn"}
BEAMLINE_PATTERNS = ["BL04I", "BL11I", "BL19I", "BL21I"]


@pytest.fixture(scope="module")
def index() -> PatternIndex:
    return pattern_index()


def _write_xml(tmp_path: Path, *components: str) -> Path:
    xml = tmp_path / "BL21I-XX-IOC-01.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n'
        + "\n".join(components)
        + "\n</components>\n"
    )
    return xml


KEPT = (
    '<BL21I.TTHBumpstripMonitor DESC="Top Bumpstrip" P="BL21I-MO-ARM-01" '
    'R=":TTH:BUMPSTRIP:TOP" name="TTH.Safety.BumpstripTop"/>'
)
NO_MODEL = (
    '<BL21I.FS1Control P="BL21I-OP-FS-01" RL-AB_SWITCH="1" RL-C_SWITCH="2" '
    'RL-D_SWITCH="3" name="FS1"/>'
)
NO_PATTERN = '<BL20J.someTemplate P="BL20J-MO-X-01" name="X"/>'


def test_convert_drops_what_the_pattern_does_not_take(tmp_path: Path):
    xml = _write_xml(tmp_path, KEPT, NO_MODEL, NO_PATTERN)
    out = tmp_path / "ioc.yaml"
    result = convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")

    text = out.read_text()
    entities = YAML(typ="safe").load(text)["entities"]
    types = [e["type"] for e in entities]
    assert "BL21I.TTHBumpstripMonitor" in types
    assert "BL21I.FS1Control" not in types
    assert not [t for t in types if t.startswith("BL20J.")]

    # the schema header stays first, and the comment lists each entity dropped
    lines = text.splitlines()
    assert lines[0].startswith("# yaml-language-server:")
    assert "DROPPED FOR MANUAL REVIEW" in text
    assert f"# Dropped: no model BL21I.FS1Control in {BL21I}" in lines
    assert "#   - type: BL21I.FS1Control" in lines
    assert "#     P: BL21I-OP-FS-01" in lines
    assert (
        f"# Dropped: no runtime pattern for BL20J in "
        f"{SUPPORT_LIBRARY}@{SUPPORT_PATTERN_TAG}"
    ) in lines
    assert "#   - type: BL20J.someTemplate" in lines

    warnings = "\n".join(result.warnings)
    assert (
        "BL21I-XX-IOC-01: dropped BL21I.FS1Control (P=BL21I-OP-FS-01) from the "
        f"ioc.yaml for manual review: no model BL21I.FS1Control in {BL21I}"
    ) in warnings
    assert "dropped BL20J.someTemplate (name=X, P=BL20J-MO-X-01)" in warnings
    # the pattern is listed, outside a services repo
    assert f"would add runtime pattern {BL21I}" in result.notes


def test_convert_without_beamline_modules_has_no_comment(tmp_path: Path):
    xml = _write_xml(tmp_path, KEPT)
    out = tmp_path / "ioc.yaml"
    result = convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")
    assert "DROPPED" not in out.read_text()
    assert not [w for w in result.warnings if "dropped" in w]


def test_rejected_entity_is_dropped_alone(index: PatternIndex):
    good = {"type": "BL21I.TTHBumpstripMonitor", "P": "A", "R": ":1", "DESC": "x"}
    bad = {**good, "R": ":2", "NOT_A_PARAM": 1}
    kept, dropped = drop_beamline_entities([good, bad, {**good, "R": ":3"}], index)
    assert [e["R"] for e in kept] == [":1", ":3"]
    assert [d.entity for d in dropped] == [bad]
    assert dropped[0].reason.startswith(f"{BL21I} rejects")
    assert "NOT_A_PARAM" in dropped[0].reason


def test_reference_to_another_module_is_accepted(index: PatternIndex):
    """An object parameter may name an id an entity of another module defines."""
    port = {"type": "asyn.AsynIP", "name": "ty_01", "port": "1.2.3.4:7001"}
    trigger = {"type": "BL11I.auto_BL11I_serial_trigger", "P": "X", "PORT": "ty_01"}
    kept, dropped = drop_beamline_entities([port, trigger], index)
    assert (kept, dropped) == ([port, trigger], [])
    assert index.plan(kept).refs == [index.patterns["BL11I"].ref]


def test_entities_referring_to_a_dropped_one_are_dropped(index: PatternIndex):
    """Through object parameters of the generic and the pattern models, in turn."""
    bl20j = {"type": "BL20J.controller", "name": "P1"}
    motor = {"type": "motor.basic_asyn_motor", "name": "M1", "PORT": "P1"}
    trigger = {"type": "BL11I.auto_BL11I_serial_trigger", "P": "X", "PORT": "M1"}
    other = {"type": "epics.EpicsEnvSet", "name": "P2", "value": "x"}
    kept, dropped = drop_beamline_entities([bl20j, motor, trigger, other], index)
    assert kept == [other]
    assert [d.reason for d in dropped][1:] == [
        "refers to P1, a dropped BL20J.controller",
        "refers to M1, a dropped motor.basic_asyn_motor",
    ]


def test_a_string_equal_to_a_dropped_name_is_no_reference(index: PatternIndex):
    """Only an object parameter of a known model refers to an entity."""
    bl20j = {"type": "BL20J.thing", "name": "GONIO"}
    env = {"type": "epics.EpicsEnvSet", "name": "STAGE", "value": "GONIO"}
    dbpf = {"type": "epics.dbpf", "pv": "X", "value": "GONIO"}
    kept, dropped = drop_beamline_entities([bl20j, env, dbpf], index)
    assert kept == [env, dbpf]
    assert [d.entity for d in dropped] == [bl20j]


def test_a_str_parameter_equal_to_a_dropped_name_is_no_reference(
    index: PatternIndex,
):
    scm10 = {"type": "BL21I.SCM10", "name": "Top Bumpstrip"}
    monitor = {
        "type": "BL21I.TTHBumpstripMonitor",
        "DESC": "Top Bumpstrip",
        "P": "A",
        "R": ":1",
    }
    kept, dropped = drop_beamline_entities([scm10, monitor], index)
    assert kept == [monitor]
    assert [d.entity for d in dropped] == [scm10]


def test_an_entity_with_no_known_model_refers_to_nothing(index: PatternIndex):
    """generate2, not builder2ibek, reports what such an entity names."""
    bl20j = {"type": "BL20J.thing", "name": "P1"}
    unknown = {"type": "noSuchModule.thing", "PORT": "P1"}
    kept, _ = drop_beamline_entities([bl20j, unknown], index)
    assert kept == [unknown]


def test_validation_failure_of_any_kind_is_a_drop(index: PatternIndex, monkeypatch):
    def broken(pattern):
        raise AttributeError("'_ForeignEntity' object has no attribute 'name'")

    monkeypatch.setattr(index, "_ioc_model", broken)
    entity = {"type": "BL21I.TTHBumpstripMonitor", "P": "A", "R": ":1", "DESC": "x"}
    kept, dropped = drop_beamline_entities([entity], index)
    assert kept == []
    assert dropped[0].reason == (
        f"{BL21I} rejects an entity: AttributeError: "
        "'_ForeignEntity' object has no attribute 'name'"
    )


def _unreachable():
    raise PatternIndexError("cannot clone: network unreachable")


def test_unindexed_libraries_fail_the_conversion(tmp_path: Path, monkeypatch):
    """Beamline entities are never dropped for a network failure."""
    monkeypatch.setattr(convert, "pattern_index", _unreachable)
    _check_unindexed_fails(tmp_path)


def test_unindexed_support_library_fails_the_conversion(
    tmp_path: Path, monkeypatch, index: PatternIndex
):
    """ibek-runtime-streamdevice indexed alone is not enough for beamline IOCs."""

    class Partial(PatternIndex):
        def __init__(self):
            self.__dict__.update(index.__dict__)
            self.failures = {SUPPORT_LIBRARY: "cannot clone: network unreachable"}

    monkeypatch.setattr(convert, "pattern_index", Partial)
    _check_unindexed_fails(tmp_path)


def test_unindexed_streamdevice_library_does_not_fail_the_conversion(
    tmp_path: Path, monkeypatch, index: PatternIndex
):
    class Partial(PatternIndex):
        def __init__(self):
            self.__dict__.update(index.__dict__)
            self.failures = {"ibek-runtime-streamdevice": "unreachable"}

    monkeypatch.setattr(convert, "pattern_index", Partial)
    out = tmp_path / "ioc.yaml"
    convert_file(_write_xml(tmp_path, KEPT), out, "/epics/ibek-defs/ioc.schema.json")
    assert "BL21I.TTHBumpstripMonitor" in out.read_text()


@pytest.mark.parametrize("where", ["index", "support library"])
def test_an_error_with_no_message_still_fails_the_conversion(
    tmp_path: Path, monkeypatch, index: PatternIndex, where: str
):
    def raise_empty():
        raise TimeoutError()

    class Partial(PatternIndex):
        def __init__(self):
            self.__dict__.update(index.__dict__)
            self.failures = {SUPPORT_LIBRARY: ""}

    monkeypatch.setattr(
        convert, "pattern_index", raise_empty if where == "index" else Partial
    )
    xml = _write_xml(tmp_path, KEPT)
    out = tmp_path / "ioc.yaml"
    reason = "TimeoutError" if where == "index" else "unknown error"
    with pytest.raises(BeamlinePatternError, match=f"for them: {reason}$"):
        convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")
    assert not out.exists()


def _check_unindexed_fails(tmp_path: Path):
    xml = _write_xml(tmp_path, KEPT, NO_PATTERN)
    out = tmp_path / "ioc.yaml"
    with pytest.raises(BeamlinePatternError, match="BL20J, BL21I.*unreachable"):
        convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")
    assert not out.exists()


def test_unindexed_libraries_fail_xml2yaml(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(convert, "pattern_index", _unreachable)
    xml = _write_xml(tmp_path, KEPT)
    out = tmp_path / "ioc.yaml"
    result = CliRunner().invoke(cli, ["xml2yaml", str(xml), "--yaml", str(out)])
    assert result.exit_code == 1
    assert "error: BL21I-XX-IOC-01 uses beamline modules BL21I" in result.output
    assert not out.exists()


def test_unindexed_libraries_do_not_matter_without_beamline_modules(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(convert, "pattern_index", _unreachable)
    assert (
        convert.drop_unpatterned_entities(dispatch(Builder(), tmp_path / "X.xml")) == []
    )


def test_other_modules_reraise_what_is_not_a_validation_error(
    index: PatternIndex, monkeypatch
):
    """Only a beamline module turns any exception into a rejection."""

    def broken(pattern):
        raise AttributeError("broken model")

    monkeypatch.setattr(index, "_ioc_model", broken)
    entity = {"type": "attocubeInterf.ids3010", "P": "X-", "PORT": "p", "Q": "01"}
    with pytest.raises(AttributeError, match="broken model"):
        index.rejects(index.patterns["attocubeInterf"], [entity])
    beamline = {"type": "BL21I.TTHBumpstripMonitor", "P": "A", "R": ":1", "DESC": "x"}
    assert "AttributeError: broken model" in index.rejects(
        index.patterns["BL21I"], [beamline]
    )


def test_plan_keeps_a_rejected_beamline_module_build_time(
    index: PatternIndex, tmp_path: Path, monkeypatch
):
    """Only when plan() is given entities drop_beamline_entities has not seen;
    add_patterns then warns rather than skip the module silently."""
    entity = {"type": "BL21I.TTHBumpstripMonitor", "P": "A", "R": ":1"}
    plan = index.plan([entity])
    assert plan.patterns == []
    assert "DESC" in plan.build_time["BL21I"]

    monkeypatch.setattr(vendor_patterns, "pattern_index", lambda: index)
    report = vendor_patterns.add_patterns([entity], tmp_path / "ioc.yaml")
    assert report.warnings == [
        f"beamline module BL21I gets no runtime pattern: {plan.build_time['BL21I']}"
    ]


def test_beamline_module_in_both_libraries_fails_the_conversion(
    tmp_path: Path, monkeypatch, index: PatternIndex
):
    class Clash(PatternIndex):
        def __init__(self):
            self.__dict__.update(index.__dict__)
            self.module_failures = {"BL21I": "BL21I has a pattern in both"}

    monkeypatch.setattr(convert, "pattern_index", Clash)
    xml = _write_xml(tmp_path, KEPT)
    with pytest.raises(BeamlinePatternError, match="BL21I has a pattern in both"):
        convert_file(xml, tmp_path / "ioc.yaml", "/epics/ibek-defs/ioc.schema.json")


def test_kept_entities_drop_the_pattern_model_defaults(tmp_path: Path):
    """Not the generic model's: GonioReady's dom defaults to 'undefined' only
    there, and the pattern requires it."""
    xml = _write_xml(
        tmp_path,
        '<BL04I.auto_GonioReady dom="undefined"/>',
        '<BL21I.SMPLValveSequence DELAY1="0" P="BL21I-EA-SMPL-01" R=":SEQ" '
        'VAC1_NAME="VALVE-01" VAC2_NAME="VALVE-16" VAC_ELEMENT1="BL21I-VA-FVALV-12" '
        'VAC_ELEMENT2="BL21I-VA-VALVE-16" VAC_ELEMENT3="BL21I-PS-SHTR-01" '
        'VAC_ELEMENT4="BL21I-VA-ABSB-02" VAC_ELEMENT5="BL21I-VA-VALVE-17" '
        'name="SEQ"/>',
    )
    out = tmp_path / "ioc.yaml"
    result = convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")
    assert not [w for w in result.warnings if "dropped" in w]
    entities = YAML(typ="safe").load(out.read_text())["entities"]
    gonio = next(e for e in entities if e["type"] == "BL04I.auto_GonioReady")
    assert gonio["dom"] == "undefined"
    seq = next(e for e in entities if e["type"] == "BL21I.SMPLValveSequence")
    assert "DELAY1" not in seq and "VAC1_NAME" not in seq
    assert seq["VAC2_NAME"] == "VALVE-16"
    assert seq["VAC_ELEMENT1"] == "BL21I-VA-FVALV-12"


def test_dropped_comment_survives_the_pattern_add_header_rewrite(tmp_path: Path):
    xml = _write_xml(tmp_path, KEPT, NO_MODEL)
    out = tmp_path / "ioc.yaml"
    convert_file(xml, out, "/epics/ibek-defs/ioc.schema.json")
    before = out.read_text()
    rewrite_ioc_yaml_header(out)
    after = out.read_text()
    assert after.splitlines()[0] == SCHEMA_HEADER
    assert after.splitlines()[1:] == before.splitlines()[1:]
    assert "#   - type: BL21I.FS1Control" in after
    YAML(typ="safe").load(after)


def test_plan_sends_beamline_modules_to_their_pattern(index: PatternIndex, monkeypatch):
    """Neither the generic model nor the alignment tables keep it build-time."""
    monkeypatch.setattr(patterns, "generic_modules", lambda: {"BL21I"})
    entity = {"type": "BL21I.TTHBumpstripMonitor", "P": "A", "R": ":1", "DESC": "x"}
    plan = index.plan([entity])
    assert plan.refs == [BL21I] and plan.build_time == {}


# -- the record types the beamline patterns load ----------------------------------

_RECORD = re.compile(r"^\s*g?record\s*\(\s*\"?([A-Za-z0-9_]+)", re.M)


def record_types(pattern: Path) -> dict[str, set[str]]:
    """Each record type the pattern's databases use, and the files using it."""
    found: dict[str, set[str]] = {}
    for db in sorted([*pattern.glob("*.template"), *pattern.glob("*.db")]):
        for record_type in _RECORD.findall(db.read_text()):
            found.setdefault(record_type, set()).add(db.name)
    return found


@pytest.mark.parametrize("module", BEAMLINE_PATTERNS)
def test_beamline_pattern_records_are_in_the_runtime_image(module: str):
    """A beamline pattern loads only records the ioc-streamdevice-runtime has."""
    found = record_types(SUPPORT_PATTERN_LIBRARY / module)
    assert found, f"no records found in {module}"
    missing = {
        t: sorted(files) for t, files in found.items() if t not in RUNTIME_IMAGE_RECORDS
    }
    assert not missing, f"{module} uses record types the image lacks: {missing}"
