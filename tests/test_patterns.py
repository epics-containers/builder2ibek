"""The runtime pattern index, and which modules builder2ibek maps to a pattern."""

import subprocess
import warnings
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from ibek.ioc import clear_entity_model_ids
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES
from ibek.render import Render
from ibek.render_db import RenderDb
from pydantic.warnings import PydanticDeprecatedSince211
from ruamel.yaml import YAML

from builder2ibek import patterns
from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from builder2ibek.patterns import (
    ALIGNED,
    GENERIC_DIFFERS,
    LIBRARIES,
    STREAMDEVICE_LIBRARY,
    SUPPORT_LIBRARY,
    Pattern,
    PatternIndex,
    PatternIndexError,
    is_beamline_module,
    latest_tag,
    pattern_index,
)
from builder2ibek.support_defaults import routes_to_support_pattern
from builder2ibek.vendor_patterns import is_pattern_only
from tests.conftest import DLS_SUPPORT, REPO_ROOT
from tests.pattern_pins import PINNED_LIBRARIES

FIXTURES = Path(__file__).parent / "patterns"

_yaml = YAML(typ="safe", pure=True)


def _load(support_yaml: Path) -> dict:
    return _yaml.load(support_yaml.read_text())


@cache
def _generic_support_yamls() -> dict[str, Path]:
    """module -> its support yaml in ibek-support*."""
    found = {}
    for support_yaml in REPO_ROOT.glob("ibek-support*/*/*.ibek.support.yaml"):
        found[_load(support_yaml)["module"]] = support_yaml
    return found


@pytest.fixture(scope="module")
def index() -> PatternIndex:
    return pattern_index()


# -- the library -----------------------------------------------------------------


@pytest.mark.parametrize("library", LIBRARIES)
def test_library_is_the_one_ibek_vendors_from(library: str):
    """The submodule the tests index is the library `ibek pattern add` clones."""
    url = subprocess.run(
        ["git", "config", "-f", ".gitmodules", f"submodule.{library}.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert url == DEFAULT_LIBRARIES[library]
    assert REPO_ROOT / library in PINNED_LIBRARIES


@pytest.mark.parametrize("submodule", PINNED_LIBRARIES, ids=lambda p: p.name)
def test_tests_index_the_pinned_tag(index: PatternIndex, submodule: Path):
    """conftest pins the tag each submodule is checked out at."""
    tag = PINNED_LIBRARIES[submodule]
    tags = subprocess.run(
        ["git", "-C", str(submodule), "tag", "--points-at", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tag in tags
    assert index.libraries[submodule.name] == tag
    assert {
        p.version for p in index.patterns.values() if p.library == submodule.name
    } == {tag}


def test_every_pattern_folder_is_indexed(index: PatternIndex):
    """Every folder, except ibek-runtime-support's of modules not routed to it."""
    for submodule in PINNED_LIBRARIES:
        folders = {p.parent.name for p in submodule.glob("*/*.ibek.support.yaml")}
        if submodule.name == SUPPORT_LIBRARY:
            folders = set(filter(routes_to_support_pattern, folders))
        indexed = {m for m, p in index.patterns.items() if p.library == submodule.name}
        assert folders and indexed == folders


def test_support_library_routes_beamline_and_areadetector_modules(
    index: PatternIndex,
):
    """ibek-runtime-support serves beamline modules and detectorPlugins, whose
    gdaPlugins model replaces the builder object gdaPlugins; BL15I-BUILDER gets
    no pattern.

    A detectorPlugins-only IOC is still never moved onto the streamdevice
    runtime image, which has no AreaDetector: it needs an AreaDetector generic
    IOC.
    """
    folders = {p.name for p in (REPO_ROOT / SUPPORT_LIBRARY).iterdir()}
    assert {"BL15I-BUILDER", "detectorPlugins"} <= folders
    assert "BL15I-BUILDER" not in index.patterns
    assert index.patterns["detectorPlugins"].library == SUPPORT_LIBRARY
    # the sub-entities an image must run, as the index loads them
    gda_subs = {
        (t, args)
        for model, t, args in index.patterns["detectorPlugins"].sub_entities
        if model == "gdaPlugins"
    }
    assert any(
        t == "ADCore.NDStats" and "ATTRIBUTES_FILE" in args for t, args in gda_subs
    )
    assert {t for t, _ in gda_subs} >= {
        "ffmpegServer.ffmpegFile",
        "ffmpegServer.ffmpegStream",
        "detectorPlugins._gdaPluginsRecords",
    }
    # skipped, but recorded so that an IOC using one gets a warning
    assert "BL15I-BUILDER" in index.unindexed
    assert "detectorPlugins" not in index.unindexed
    gda = {
        "type": "detectorPlugins.gdaPlugins",
        "P": "X",
        "CAM": "CAM",
        "PORTPREFIX": "D",
    }
    plan = index.plan([gda, {"type": "BL15I-BUILDER.auto_BL15I_SumTheDiode"}])
    assert plan.refs == [index.patterns["detectorPlugins"].ref]
    assert plan.build_time == {}
    # every type the runtime image could have, and still not pattern-only
    runtime_types = frozenset({"detectorPlugins.gdaPlugins", "epics.dbpf"})
    assert not is_pattern_only([gda], plan, runtime_types)


def test_beamline_modules():
    beamline = ["BL04I", "BL11I", "BL19I", "BL21I", "BL20J"]
    other = ["BL15I-BUILDER", "BL46P-BUILDER", "I19Server", "BLGui"]
    assert all(map(is_beamline_module, beamline))
    assert not any(map(is_beamline_module, other))


def test_beamline_patterns_are_in_ibek_runtime_support(index: PatternIndex):
    beamline = {m: p for m, p in index.patterns.items() if is_beamline_module(m)}
    assert {"BL04I", "BL11I", "BL19I", "BL21I"} <= beamline.keys()
    assert {p.library for p in beamline.values()} == {SUPPORT_LIBRARY}


def _ls_remote(*tags: str) -> subprocess.CompletedProcess:
    out = "".join(f"0123abcd\trefs/tags/{t}\n" for t in tags)
    return subprocess.CompletedProcess([], 0, out, "")


def test_latest_tag_is_the_highest_release():
    tags = ("0.7.3", "0.10.0", "0.9.1", "1.0.0-beta.1", "1.0.0rc1")
    with patch.object(patterns.subprocess, "run", return_value=_ls_remote(*tags)):
        assert latest_tag("url") == "0.10.0"
    tags = ("2.8.26ec8", "2.8.26ec10", "2.8.26ec11-beta.1", "0.1.0-beta.1")
    with patch.object(patterns.subprocess, "run", return_value=_ls_remote(*tags)):
        assert latest_tag("url") == "2.8.26ec10"


def test_latest_tag_unreachable():
    failed = subprocess.CompletedProcess([], 128, "", "not found")
    with patch.object(patterns.subprocess, "run", return_value=failed):
        with pytest.raises(PatternIndexError, match="cannot list the tags"):
            latest_tag("url")


def _fake_clones(modules: dict[str, str | list[str]]):
    """A subprocess.run that clones each library with these pattern folders."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "ls-remote":
            return _ls_remote("0.7.3", "0.8.1")
        library = next(lib for lib in LIBRARIES if cmd[-1] == DEFAULT_LIBRARIES[lib])
        folders = modules[library]
        for module in [folders] if isinstance(folders, str) else folders:
            clone = Path(kwargs["cwd"]) / library / module
            clone.mkdir(parents=True)
            (clone / f"{module}.ibek.support.yaml").write_text(
                f"module: {module}\nentity_models: [{{name: bar}}]\n"
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run, calls


@pytest.mark.parametrize("override", ["0.7.3", ""])
def test_pattern_index_clones_the_tag(monkeypatch, override: str):
    """Each library's override tag, else its latest, is shallow-cloned and indexed."""
    for tag_env in LIBRARIES.values():
        monkeypatch.setenv(tag_env, override)
    run, calls = _fake_clones({STREAMDEVICE_LIBRARY: "foo", SUPPORT_LIBRARY: "BL99X"})

    pattern_index.cache_clear()
    try:
        with patch.object(patterns.subprocess, "run", side_effect=run):
            index = pattern_index()
    finally:
        pattern_index.cache_clear()
    tag = override or "0.8.1"
    clones = [c for c in calls if c[:2] == ["git", "clone"]]
    assert [c[-3:] for c in clones] == [
        ["--branch", tag, DEFAULT_LIBRARIES[library]] for library in LIBRARIES
    ]
    assert len(calls) == (2 if override else 4)
    assert index.patterns["foo"].ref == f"{STREAMDEVICE_LIBRARY}:foo@{tag}"
    assert index.patterns["BL99X"].ref == f"{SUPPORT_LIBRARY}:BL99X@{tag}"
    assert index.patterns["foo"].models == {"bar"}


def test_beamline_module_in_both_libraries_fails_only_that_module(monkeypatch, capsys):
    """ibek-runtime-support is left out for the module; nothing else is lost."""
    for tag_env in LIBRARIES.values():
        monkeypatch.setenv(tag_env, "1.0.0")
    run, _ = _fake_clones(
        {STREAMDEVICE_LIBRARY: ["foo", "BL99X"], SUPPORT_LIBRARY: ["BL98X", "BL99X"]}
    )
    pattern_index.cache_clear()
    try:
        with patch.object(patterns.subprocess, "run", side_effect=run):
            index = pattern_index()
    finally:
        pattern_index.cache_clear()
    both = (
        f"BL99X has a pattern in both {STREAMDEVICE_LIBRARY}:BL99X@1.0.0 and "
        f"{SUPPORT_LIBRARY}:BL99X@1.0.0"
    )
    assert index.module_failures == {"BL99X": both}
    assert f"warning: {both}" in capsys.readouterr().err
    assert index.failures == {}
    assert index.patterns["foo"].library == STREAMDEVICE_LIBRARY
    assert index.patterns["BL98X"].library == SUPPORT_LIBRARY
    assert index.patterns["BL99X"].library == STREAMDEVICE_LIBRARY


def test_ref_is_what_ibek_pattern_add_takes(index: PatternIndex):
    pattern = index.patterns["attocubeInterf"]
    assert pattern.library == "ibek-runtime-streamdevice"
    assert pattern.ref == f"ibek-runtime-streamdevice:attocubeInterf@{pattern.version}"
    assert "ids3010" in pattern.models


def test_models_are_read_from_the_support_yaml(index: PatternIndex):
    for pattern in index.patterns.values():
        data = _load(pattern.support_yaml)
        assert pattern.models == {m["name"] for m in data["entity_models"]}


def test_folder_must_match_module(tmp_path: Path):
    folder = tmp_path / "foo"
    folder.mkdir()
    (folder / "foo.ibek.support.yaml").write_text("module: bar\nentity_models: []\n")
    with pytest.raises(PatternIndexError, match="declares module 'bar'"):
        PatternIndex(tmp_path, "1.0.0")


def test_missing_library_is_an_error(tmp_path: Path):
    with pytest.raises(PatternIndexError, match="no patterns found"):
        PatternIndex(tmp_path, "1.0.0")


# -- which modules map to a pattern --------------------------------------------


def test_tables_name_patterns(index: PatternIndex):
    assert not ALIGNED & GENERIC_DIFFERS
    assert ALIGNED | GENERIC_DIFFERS <= index.patterns.keys()


def test_tables_cover_every_module_with_a_generic_model(index: PatternIndex):
    """Each pattern that also has a generic model is decided one way or the other.

    The decision is a written table, not a lookup in ibek-support*, because CI
    has only a vendored subset of ibek-support-dls. So the full comparison runs
    only where the real submodule is checked out.
    """
    # a beamline module goes to its pattern whatever its generic model
    overlap = {
        m
        for m in index.patterns.keys() & _generic_support_yamls().keys()
        if not is_beamline_module(m)
    }
    decided = ALIGNED | GENERIC_DIFFERS
    assert overlap <= decided, f"undecided: {sorted(overlap - decided)}"
    if (DLS_SUPPORT / ".git").exists():
        assert decided == overlap, f"no generic model: {sorted(decided - overlap)}"


# Changes of parameter type that still accept what builder2ibek emits for the
# generic model: an object reference is written as the referenced entity's name.
_ACCEPTED_TYPE_CHANGES = {("object", "str"), ("int", "float")}
_NO_DEFAULT = object()


def _differences(generic: Path, pattern: Path) -> list[str]:
    """How the pattern model fails to take an entity of the generic one unchanged."""
    pattern_models = {m["name"]: m for m in _load(pattern)["entity_models"]}
    problems = []
    for model in _load(generic)["entity_models"]:
        name = model["name"]
        if name not in pattern_models:
            problems.append(f"no model {name}")
            continue
        g_params = model.get("parameters") or {}
        p_params = pattern_models[name].get("parameters") or {}
        for param, spec in g_params.items():
            if param.startswith("gda_"):  # globalHandler strips these
                continue
            if param not in p_params:
                problems.append(f"{name}: no parameter {param}")
                continue
            p_spec = p_params[param]
            change = (spec.get("type"), p_spec.get("type"))
            if change[0] != change[1] and change not in _ACCEPTED_TYPE_CHANGES:
                problems.append(f"{name}.{param}: {change[0]} -> {change[1]}")
            elif spec.get("values") != p_spec.get("values"):
                problems.append(f"{name}.{param}: enum values differ")
            # builder2ibek drops a value equal to the generic default, so the
            # pattern must fall back to the same one
            if "default" in spec and spec["default"] != p_spec.get(
                "default", _NO_DEFAULT
            ):
                problems.append(f"{name}.{param}: default differs")
        for param, spec in p_params.items():
            if param not in g_params and "default" not in spec:
                problems.append(f"{name}: new required parameter {param}")
    return problems


@pytest.mark.parametrize("module", sorted(ALIGNED | GENERIC_DIFFERS))
def test_alignment_matches_the_models(index: PatternIndex, module: str):
    """ALIGNED holds exactly the patterns that take the generic model unchanged.

    A library release that aligns a module fails this until the module moves
    from GENERIC_DIFFERS to ALIGNED.
    """
    generic = _generic_support_yamls().get(module)
    if generic is None:
        pytest.skip(f"no generic model for {module} in this checkout")
    problems = _differences(generic, index.patterns[module].support_yaml)
    if module in ALIGNED:
        assert not problems, f"{module} is in ALIGNED but: {problems}"
    else:
        assert problems, f"{module} matches its generic model; move it to ALIGNED"


def _convert(xml: Path) -> list[dict]:
    builder = Builder()
    builder.load(xml)
    return [dict(e) for e in dispatch(builder, xml).entities]


# One builder XML per pattern module that real builder XMLs use, named after the
# module builder2ibek emits, holding components copied from real IOC XMLs (a
# comment in each names its source). Each checks that the pattern's models follow
# the module's etc/builder.py: what builder2ibek converts from builder XML must
# validate against the pattern and load records.

# Fixtures that fail against the pinned library release, with the reason the
# pattern audit gave and the change that fixes it. Each turns into a pass once
# the fix is released and the pin moves; then drop it from here.
_SD = "https://github.com/epics-containers/ibek-runtime-streamdevice/pull/"
_PENDING = "a fix in ibek-runtime-streamdevice, not yet in a PR"
XFAIL: dict[str, tuple[str, str]] = {
    "caenN1470": (
        "only the private _caenN1470/_chan helpers are modelled, not caenN1470",
        _PENDING,
    ),
    "chillax": ("chillaxController loads no databases", _PENDING),
    "d2afe": (
        "no d2afe model, only the raw d2ptg template; d2afe needs compiled code, "
        "so it moves to ibek-support-dls",
        _PENDING,
    ),
    "digitelMpc": (
        "raw template import: the controller has no name id, Ionp a flat MPC",
        _PENDING,
    ),
    "granvillePhillips": (
        "gauges take a flat port, not GCTLR",
        f"{_SD}53, released in 0.9.0, with "
        "https://github.com/epics-containers/builder2ibek/pull/216",
    ),
    "keithley2400": ('SCAN is an int; builder XMLs pass SCAN=".1"', _PENDING),
    "Keithley6487": ('A is a required int; builder XMLs set A=""', _PENDING),
    "keysightLCR": ('SCAN is an int; builder XMLs pass SCAN=".1"', _PENDING),
    "knauer": ("no model for the GUI-only PumpAndValve class", _PENDING),
    "lakeshore331": ("ONOFFDEFAULT is an int; builder XMLs pass 'OFF'", _PENDING),
    "lakeshore340": (
        "no name id; SCAN and TEMPSCAN are ints, builder XMLs pass .5",
        _PENDING,
    ),
    "leybold": (
        "DRVH and DRVL are required; centerOne.xml leaves them out (and the "
        "leybold converter reads centerOne.xml from /dls_sw, absent in CI)",
        _PENDING,
    ),
    "mks937a": (
        "raw template import: a flat port, not GCTLR; template names, not the "
        "auto_ classes",
        f"{_SD}54",
    ),
    "mks937b": (
        "raw template import: a flat port, not GCTLR; no name id on the controller",
        f"{_SD}54",
    ),
    "motomanNX100": (
        "no model for the BL11I templates auto_BL11I_barcode and "
        "auto_BL11I_robot_interlocks, which belong in the BL11I runtime pattern",
        _PENDING,
    ),
    "PIpiezo": (
        "imported from PIpiezo 1-23, so no auto_actuatorcallback (1-28's name)",
        _PENDING,
    ),
    "yaskawaBARTRobot": (
        "models the I22-only release; 0-1 builder XMLs leave out CUR_COLUMN_VAR_NUM",
        _PENDING,
    ),
}

# Models that load no records by design: they only give a screen
RENDERS_NOTHING: frozenset[str] = frozenset()


def _fixture_params() -> list:
    return [
        pytest.param(
            fixture,
            id=fixture.stem,
            marks=[pytest.mark.xfail(reason="; fixed by ".join(XFAIL[fixture.stem]))]
            if fixture.stem in XFAIL
            else [],
        )
        for fixture in sorted(FIXTURES.glob("*.xml"))
    ]


def _renders_nothing(
    index: PatternIndex, pattern: Pattern, entities: list[Mapping[str, Any]]
) -> list[str]:
    """The types of the entities that load no records and run no commands."""
    clear_entity_model_ids()
    try:
        with warnings.catch_warnings():
            # raised from inside ibek's Entity, as in PatternIndex.rejects
            warnings.simplefilter("ignore", PydanticDeprecatedSince211)
            ioc = index._ioc_model(pattern)(
                ioc_name="validate",
                description="validate",
                entities=[dict(e) for e in entities],
            )
        render = Render()
        silent = []
        for entity in ioc.entities:
            model = entity._model
            if model.sub_entities or f"{pattern.module}.{model.name}" in (
                RENDERS_NOTHING
            ):
                continue
            outputs = [
                RenderDb([entity]).render_database(),
                render.render_pre_ioc_init(entity),
                render.render_post_ioc_init(entity),
            ]
            if not any(outputs):
                silent.append(str(entity.type))
        return silent
    finally:
        clear_entity_model_ids()


@pytest.mark.parametrize("fixture", _fixture_params())
def test_converted_xml_fits_the_pattern(index: PatternIndex, fixture: Path):
    module = fixture.stem
    pattern = index.patterns[module]
    entities = _convert(fixture)
    ours: list[Mapping[str, Any]] = [
        e for e in entities if patterns.module_of(e) == module
    ]
    assert ours, f"{fixture.name} converts to no {module} entity"

    reason = index.rejects(pattern, ours, index.foreign_ids(ours))
    assert not reason, reason
    silent = _renders_nothing(index, pattern, ours)
    assert not silent, f"no records or commands from {silent}"

    # where no generic model competes, builder2ibek uses the pattern
    if module in ALIGNED or module not in patterns.generic_modules():
        plan = index.plan(entities)
        assert plan.build_time == {}
        assert plan.patterns == [pattern]


def test_every_aligned_module_has_a_fixture():
    assert {p.stem for p in FIXTURES.glob("*.xml")} >= ALIGNED


def test_xfails_name_fixtures():
    assert set(XFAIL) <= {p.stem for p in FIXTURES.glob("*.xml")}


# -- the plan for one IOC -------------------------------------------------------


def _ids3010(**params) -> dict:
    return {"type": "attocubeInterf.ids3010", "P": "X-", "PORT": "p", **params}


def test_plan_pattern_only_module(index: PatternIndex):
    plan = index.plan(
        [
            {"type": "epics.EpicsEnvSet", "name": "EPICS_TZ", "value": "GMT0BST"},
            _ids3010(Q="01"),
            _ids3010(Q="02"),
        ]
    )
    assert plan.refs == [index.patterns["attocubeInterf"].ref]
    assert plan.build_time == {}


def test_plan_keeps_order_of_first_use(index: PatternIndex):
    scroll = {"type": "EdwardsScroll.EdwardsScroll", "P": "X", "port": "p"}
    plan = index.plan([scroll, _ids3010(Q="01")])
    assert [p.module for p in plan.patterns] == ["EdwardsScroll", "attocubeInterf"]


@pytest.mark.parametrize("module", sorted(GENERIC_DIFFERS))
def test_plan_differing_module_stays_build_time(index: PatternIndex, module: str):
    model = sorted(index.patterns[module].models)[0]
    plan = index.plan([{"type": f"{module}.{model}"}])
    assert plan.patterns == []
    assert "differs from the generic model" in plan.build_time[module]


def test_plan_rejected_entity_keeps_the_module_build_time(index: PatternIndex):
    # one entity carries a parameter the pattern model does not have
    assert index.plan([_ids3010(Q="01")]).patterns
    plan = index.plan([_ids3010(Q="01"), _ids3010(Q="02", OFFSET4=1)])
    assert plan.patterns == []
    assert "rejects" in plan.build_time["attocubeInterf"]
    assert "OFFSET4" in plan.build_time["attocubeInterf"]


def test_plan_model_missing_from_pattern(index: PatternIndex):
    entities = _convert(FIXTURES / "enzLoCuM4.xml") + [
        {"type": "enzLoCuM4.noSuchModel", "device": "X"}
    ]
    plan = index.plan(entities)
    assert plan.patterns == []
    assert "no model enzLoCuM4.noSuchModel" in plan.build_time["enzLoCuM4"]


def test_plan_leaves_no_ids_registered(index: PatternIndex):
    from ibek.ioc import id_to_entity

    index.plan(_convert(FIXTURES / "attocubeInterf.xml"))
    assert id_to_entity == {}


def test_plan_ignores_modules_without_patterns(index: PatternIndex):
    plan = index.plan(
        [{"type": "epics.EpicsEnvSet"}, {"type": "devIocStats.iocAdminSoft"}]
    )
    assert plan.patterns == [] and plan.build_time == {}


def test_plan_untabled_module_with_a_generic_model_stays_build_time(
    index: PatternIndex, monkeypatch
):
    """A newer library's pattern for a module with a generic model is not used
    until the tables decide it; a module with no generic model is."""
    monkeypatch.setattr(patterns, "generic_modules", lambda: {"attocubeInterf"})
    plan = index.plan([_ids3010(Q="01")])
    assert plan.patterns == []
    assert "not yet aligned" in plan.build_time["attocubeInterf"]

    monkeypatch.setattr(patterns, "generic_modules", lambda: set())
    assert index.plan([_ids3010(Q="01")]).refs == [index.patterns["attocubeInterf"].ref]


def test_generic_modules_are_read_from_the_module_field(tmp_path: Path):
    folder = tmp_path / "ibek-support" / "iocStats"
    folder.mkdir(parents=True)
    (folder / "iocStats.ibek.support.yaml").write_text("# x\nmodule: devIocStats\n")
    assert patterns.generic_modules(tmp_path) == {"devIocStats"}


def test_no_generic_models_warns(tmp_path: Path, capsys):
    assert patterns.generic_modules(tmp_path) == frozenset()
    assert "no ibek-support* checkout" in capsys.readouterr().err


def test_index_failure_is_cached(monkeypatch):
    """A beamline reconvert does not retry an unreachable library for every IOC."""
    for tag_env in LIBRARIES.values():
        monkeypatch.delenv(tag_env)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0" and kwargs["timeout"]
        return subprocess.CompletedProcess(cmd, 128, "", "unreachable")

    pattern_index.cache_clear()
    try:
        with patch.object(patterns.subprocess, "run", side_effect=run):
            for _ in range(2):
                with pytest.raises(PatternIndexError, match="unreachable"):
                    pattern_index()
    finally:
        pattern_index.cache_clear()
    # one ls-remote per library
    assert len(calls) == len(LIBRARIES)


@pytest.mark.parametrize("failing", list(LIBRARIES))
def test_each_library_is_indexed_on_its_own(monkeypatch, failing: str):
    """A library that cannot be cloned costs nothing of the other's patterns."""
    for tag_env in LIBRARIES.values():
        monkeypatch.setenv(tag_env, "1.0.0")
    good, calls = _fake_clones({STREAMDEVICE_LIBRARY: "foo", SUPPORT_LIBRARY: "BL99X"})

    def run(cmd, **kwargs):
        if cmd[-1] == DEFAULT_LIBRARIES[failing]:
            return subprocess.CompletedProcess(cmd, 128, "", "unreachable")
        return good(cmd, **kwargs)

    pattern_index.cache_clear()
    try:
        with patch.object(patterns.subprocess, "run", side_effect=run):
            index = pattern_index()
    finally:
        pattern_index.cache_clear()
    assert set(index.failures) == {failing}
    assert "unreachable" in index.failures[failing]
    indexed = {p.library for p in index.patterns.values()}
    assert indexed == set(LIBRARIES) - {failing}


def test_aligned_module_with_a_default_conflict_stays_build_time(
    index: PatternIndex, monkeypatch
):
    """An ALIGNED module whose entity leaves a parameter to a generic default
    the pattern does not share stays build-time."""
    module = "oxCryo"
    assert module in ALIGNED
    entities = _convert(FIXTURES / f"{module}.xml")
    assert index.plan(entities).patterns == [index.patterns[module]]

    # the first entity with a parameter the pattern defaults, which
    # builder2ibek would leave out of the entity if its value were the generic
    # default
    entity, left_out = next(
        (e, sorted(p for p in params if "default" in params[p])[0])
        for e in entities
        if str(e["type"]).startswith(f"{module}.")
        and (params := index.param_specs(str(e["type"])))
        and any("default" in spec for spec in params.values())
    )
    entities = [
        {k: v for k, v in e.items() if e is not entity or k != left_out}
        for e in entities
    ]
    monkeypatch.setattr(
        patterns, "entity_defaults", lambda t: {left_out: "not the pattern's"}
    )
    plan = index.plan(entities)
    assert plan.patterns == []
    assert f"{entity['type']}.{left_out} defaults to" in plan.build_time[module]


def test_beamline_module_has_no_default_conflict(index: PatternIndex, monkeypatch):
    """A beamline entity's defaults are stripped against its pattern model, not
    the generic one, so the generic default check does not apply to it."""
    monkeypatch.setattr(
        PatternIndex, "default_conflicts", lambda self, p, e: "a default conflict"
    )
    entity = {"type": "BL21I.TTHBumpstripMonitor", "P": "X", "R": ":Y", "DESC": "d"}
    assert index.plan([entity]).patterns == [index.patterns["BL21I"]]
