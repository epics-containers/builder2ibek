"""The runtime pattern index, and which modules builder2ibek maps to a pattern."""

import subprocess
from functools import cache
from pathlib import Path

import pytest
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES
from ruamel.yaml import YAML

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from builder2ibek.patterns import (
    ALIGNED,
    GENERIC_DIFFERS,
    LIBRARIES,
    PatternIndex,
    PatternIndexError,
    pattern_index,
)
from tests.conftest import DLS_SUPPORT, REPO_ROOT

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


# -- the libraries --------------------------------------------------------------


@pytest.mark.parametrize("library", LIBRARIES)
def test_library_is_the_one_ibek_vendors_from(library: str):
    """The index must read the same library `ibek pattern add` clones."""
    url = subprocess.run(
        ["git", "config", "-f", ".gitmodules", f"submodule.{library}.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert url == DEFAULT_LIBRARIES[library]
    path = subprocess.run(
        ["git", "config", "-f", ".gitmodules", f"submodule.{library}.path"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # a path matching ibek-support* would feed the patterns to update-schema
    assert path == library and not path.startswith("ibek-support")


def test_libraries_in_ibek_probe_order():
    assert list(LIBRARIES) == [n for n in DEFAULT_LIBRARIES if n in LIBRARIES]


@pytest.mark.parametrize("library", LIBRARIES)
def test_every_pattern_folder_is_indexed(index: PatternIndex, library: str):
    folders = {
        p.parent.name for p in (REPO_ROOT / library).glob("*/*.ibek.support.yaml")
    }
    indexed = {p.module for p in index.patterns.values() if p.library == library}
    assert folders and indexed == folders


@pytest.mark.parametrize("library", LIBRARIES)
def test_patterns_pinned_at_a_release_tag(index: PatternIndex, library: str):
    tags = subprocess.run(
        ["git", "-C", str(REPO_ROOT / library), "tag", "--points-at", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    versions = {p.version for p in index.patterns.values() if p.library == library}
    assert len(versions) == 1 and versions <= set(tags)


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
    for library in LIBRARIES:
        folder = tmp_path / library / "foo"
        folder.mkdir(parents=True)
        (folder / "foo.ibek.support.yaml").write_text(
            "module: bar\nentity_models: []\n"
        )
        git = ["git", "-C", str(tmp_path / library)]
        ident = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, *ident, "commit", "-qm", "x"], check=True)
        subprocess.run([*git, "tag", "1.0.0"], check=True)
    with pytest.raises(PatternIndexError, match="declares module 'bar'"):
        PatternIndex(tmp_path)


def test_missing_library_is_an_error(tmp_path: Path):
    with pytest.raises(PatternIndexError, match="git submodule update --init"):
        PatternIndex(tmp_path)


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
        assert problems, f"{module} now matches its generic model; move it to ALIGNED"


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
