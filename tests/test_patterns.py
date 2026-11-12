"""The runtime pattern index, and which modules builder2ibek maps to a pattern."""

import subprocess
from functools import cache
from pathlib import Path
from unittest.mock import patch

import pytest
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES
from ruamel.yaml import YAML

from builder2ibek import patterns
from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from builder2ibek.patterns import (
    ALIGNED,
    GENERIC_DIFFERS,
    LIBRARY,
    LIBRARY_TAG_ENV,
    LIBRARY_URL,
    PatternIndex,
    PatternIndexError,
    latest_tag,
    pattern_index,
)
from tests.conftest import DLS_SUPPORT, REPO_ROOT
from tests.pattern_pins import PATTERN_LIBRARY, PATTERN_TAG

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


def test_library_is_the_one_ibek_vendors_from():
    """The submodule the tests index is the library `ibek pattern add` clones."""
    url = subprocess.run(
        ["git", "config", "-f", ".gitmodules", f"submodule.{LIBRARY}.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert url == DEFAULT_LIBRARIES[LIBRARY] == LIBRARY_URL


def test_tests_index_the_pinned_tag(index: PatternIndex):
    """conftest pins the tag the submodule is checked out at."""
    tags = subprocess.run(
        ["git", "-C", str(PATTERN_LIBRARY), "tag", "--points-at", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert PATTERN_TAG in tags
    assert {p.version for p in index.patterns.values()} == {PATTERN_TAG}


def test_every_pattern_folder_is_indexed(index: PatternIndex):
    folders = {p.parent.name for p in PATTERN_LIBRARY.glob("*/*.ibek.support.yaml")}
    assert folders and set(index.patterns) == folders


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


@pytest.mark.parametrize("override", ["0.7.3", ""])
def test_pattern_index_clones_the_tag(monkeypatch, override: str):
    """The override tag, else the latest, is shallow-cloned and indexed."""
    monkeypatch.setenv(LIBRARY_TAG_ENV, override)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "ls-remote":
            return _ls_remote("0.7.3", "0.8.1")
        clone = Path(kwargs["cwd"]) / LIBRARY / "foo"
        clone.mkdir(parents=True)
        (clone / "foo.ibek.support.yaml").write_text(
            "module: foo\nentity_models: [{name: bar}]\n"
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    pattern_index.cache_clear()
    try:
        with patch.object(patterns.subprocess, "run", side_effect=run):
            index = pattern_index()
    finally:
        pattern_index.cache_clear()
    tag = override or "0.8.1"
    assert calls[-1][:2] == ["git", "clone"] and calls[-1][-3:] == [
        "--branch",
        tag,
        LIBRARY_URL,
    ]
    assert len(calls) == (1 if override else 2)
    assert index.patterns["foo"].ref == f"{LIBRARY}:foo@{tag}"
    assert index.patterns["foo"].models == {"bar"}


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
    overlap = index.patterns.keys() & _generic_support_yamls().keys()
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


# One builder XML per module, named after the module builder2ibek emits, holding
# components copied from real IOC XMLs.
@pytest.mark.parametrize(
    "fixture", sorted(FIXTURES.glob("*.xml")), ids=lambda p: p.stem
)
def test_converted_xml_maps_to_the_pattern(index: PatternIndex, fixture: Path):
    module = fixture.stem
    entities = _convert(fixture)
    assert any(str(e["type"]).startswith(f"{module}.") for e in entities)
    plan = index.plan(entities)
    assert plan.build_time == {}
    assert plan.patterns == [index.patterns[module]]


def test_every_aligned_module_has_a_fixture():
    assert {p.stem for p in FIXTURES.glob("*.xml")} >= ALIGNED


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
    # the pattern requires Q, which the builder XML may leave out
    plan = index.plan([_ids3010(Q="01"), _ids3010()])
    assert plan.patterns == []
    assert "rejects" in plan.build_time["attocubeInterf"]
    assert "Q" in plan.build_time["attocubeInterf"]


def test_plan_model_missing_from_pattern(index: PatternIndex):
    entities = _convert(FIXTURES / "enzLoCuM4.xml") + [
        {"type": "enzLoCuM4.auto_enzLoCuM4Readback", "device": "X"}
    ]
    plan = index.plan(entities)
    assert plan.patterns == []
    assert "no model enzLoCuM4.auto_enzLoCuM4Readback" in plan.build_time["enzLoCuM4"]


def test_plan_leaves_no_ids_registered(index: PatternIndex):
    from ibek.ioc import id_to_entity

    index.plan(_convert(FIXTURES / "attocubeInterf.xml"))
    assert id_to_entity == {}


def test_plan_ignores_modules_without_patterns(index: PatternIndex):
    plan = index.plan(
        [{"type": "epics.EpicsEnvSet"}, {"type": "devIocStats.iocAdminSoft"}]
    )
    assert plan.patterns == [] and plan.build_time == {}
