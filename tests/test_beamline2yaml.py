"""Tests for builder2ibek.beamline2yaml, offline: the pattern index, the image
schemas and the generic IOC releases are faked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from builder2ibek import beamline2yaml as b2y
from builder2ibek.convert import ConvertResult
from builder2ibek.patterns import (
    STREAMDEVICE_LIBRARY,
    SUPPORT_LIBRARY,
    Pattern,
    PatternPlan,
)
from builder2ibek.vendor_patterns import ModuleStatus

SAMPLES = Path(__file__).parent / "samples"
XML = SAMPLES / "BL11I-CS-IOC-09.xml"
RUNTIME = "ghcr.io/epics-containers/ioc-streamdevice-runtime:1.0"
BASE = frozenset({"epics.EpicsEnvSet", "devIocStats.iocAdminSoft", "asyn.AsynIP"})
ALL = "ghcr.io/org/ioc-all:1"


def cand(name: str, types: set[str], streamdevice: bool = False) -> b2y.Candidate:
    generic = b2y.GenericImage(f"org/{name}", f"ghcr.io/org/{name}", streamdevice)
    return b2y.Candidate(generic, f"ghcr.io/org/{name}:1", frozenset(BASE | types))


def pattern(module: str, library: str = STREAMDEVICE_LIBRARY) -> Pattern:
    return Pattern(library, module, "0.1", frozenset(), XML)


def plan_of(*modules: str, library: str = STREAMDEVICE_LIBRARY) -> PatternPlan:
    return PatternPlan([pattern(m, library) for m in modules])


CANDS = [
    cand("ioc-generic", set()),
    cand("ioc-streamdevice", set(), streamdevice=True),
    cand("ioc-pmac", {"pmac.GeoBrick", "motor.motorRecord"}),
    cand("ioc-big", {"pmac.GeoBrick", "motor.motorRecord", "dlsPLC.read100"}),
]


def ents(*types: str) -> list[dict]:
    return [{"type": t} for t in ("epics.EpicsEnvSet", *types)]


def test_smallest_covering_image():
    choice = b2y.choose_image(ents("pmac.GeoBrick"), PatternPlan(), BASE, CANDS)
    assert choice.image == "ghcr.io/org/ioc-pmac:1"
    entities = ents("pmac.GeoBrick", "dlsPLC.read100")
    choice = b2y.choose_image(entities, PatternPlan(), BASE, CANDS)
    assert choice.image == "ghcr.io/org/ioc-big:1"
    assert choice.types == CANDS[3].types


def test_base_only_ioc_gets_the_first_listed():
    choice = b2y.choose_image(ents(), PatternPlan(), BASE, CANDS)
    assert choice.image == "ghcr.io/org/ioc-generic:1"


def test_pattern_only():
    choice = b2y.choose_image(ents("stanford.SR570"), plan_of("stanford"), BASE, CANDS)
    assert choice.pattern_only and not choice.image
    assert choice.types == BASE


def test_beamline_patterns_can_make_an_ioc_pattern_only():
    plan = plan_of("BL08I", library=SUPPORT_LIBRARY)
    choice = b2y.choose_image(ents("BL08I.HomingPlcStep"), plan, BASE, CANDS)
    assert choice.pattern_only


def test_streamdevice_pattern_needs_streamdevice():
    # a mixed IOC: the StreamDevice pattern needs an image with StreamDevice
    entities = ents("stanford.SR570", "dlsPLC.read100")
    cands = [*CANDS, cand("ioc-vac", {"dlsPLC.read100"}, streamdevice=True)]
    choice = b2y.choose_image(entities, plan_of("stanford"), BASE, cands)
    assert choice.image == "ghcr.io/org/ioc-vac:1"
    choice = b2y.choose_image(entities, plan_of("stanford"), BASE, CANDS)
    assert not choice.image
    assert "no StreamDevice" in choice.detail


def test_an_image_that_installs_the_pattern_needs_no_streamdevice():
    entities = ents("stanford.SR570", "dlsPLC.read100")
    cands = [cand("ioc-vac", {"dlsPLC.read100", "stanford.SR570"})]
    choice = b2y.choose_image(entities, plan_of("stanford"), BASE, cands)
    assert choice.image == "ghcr.io/org/ioc-vac:1"


def test_support_pattern_types_are_not_needed_from_the_image():
    entities = ents("pmac.GeoBrick", "BL08I.HomingPlcStep")
    plan = plan_of("BL08I", library=SUPPORT_LIBRARY)
    choice = b2y.choose_image(entities, plan, BASE, CANDS)
    assert choice.image == "ghcr.io/org/ioc-pmac:1"


def test_no_image_reports_missing_types():
    entities = ents("pmac.GeoBrick", "opto22.opto22")
    choice = b2y.choose_image(entities, PatternPlan(), BASE, CANDS)
    assert not choice.image
    assert choice.missing == ["opto22.opto22"]
    assert "ioc-pmac" in choice.detail


def test_dockerfile_modules_after_and_and_continuations():
    dockerfile = (
        "RUN ansible.sh asyn\n"
        "RUN ansible.sh dlsPLC && ansible.sh FINS\n"
        "RUN ansible.sh vdct --tags x && \\\n    ansible.sh mks937b\n"
    )
    found = [name for name, _ in b2y.ANSIBLE_RE.findall(dockerfile)]
    assert found == ["asyn", "dlsPLC", "FINS", "vdct", "mks937b"]


def test_gitlab_candidate_reads_the_dockerfile(monkeypatch):
    dockerfile = (
        "RUN ansible.sh asyn\nRUN ansible.sh dlsPLC\nRUN ansible.sh vdct --tags x\n"
    )

    def get(host, path):
        if "releases" in path:
            return json.dumps({"tag_name": "2026.1.1"}).encode()
        assert "ref=2026.1.1" in path
        return dockerfile.encode()

    monkeypatch.setattr(b2y, "_gitlab_get", get)
    monkeypatch.setattr(
        b2y,
        "support_models",
        lambda: {
            "dlsPLC": frozenset({"dlsPLC.read100"}),
            "vdct": frozenset({"vdct.x"}),
        },
    )
    generic = b2y.GenericImage("g/ioc-vac", "reg/ioc-vac", gitlab="gitlab.example")
    got = b2y._gitlab_candidate(generic, BASE)
    assert got.ref == "reg/ioc-vac:2026.1.1"
    assert got.types == BASE | {"dlsPLC.read100"}


def test_gitlab_candidate_unreachable(monkeypatch):
    def get(host, path):
        raise OSError("401")

    monkeypatch.setattr(b2y, "_gitlab_get", get)
    generic = b2y.GenericImage("g/ioc-vac", "reg/ioc-vac", gitlab="gitlab.example")
    got = b2y._gitlab_candidate(generic, BASE)
    assert got.types is None and got.failed and "GITLAB_TOKEN" in got.problem


def test_gitlab_candidate_without_base_types():
    generic = b2y.GenericImage("g/ioc-vac", "reg/ioc-vac", gitlab="gitlab.example")
    got = b2y._gitlab_candidate(generic, frozenset())
    assert got.types is None and got.failed
    assert "ioc-generic's ioc schema is unavailable" in got.problem


def test_candidates_fall_back_to_the_latest_tag(monkeypatch):
    """A release that cannot be read falls back to the highest tag, and is a
    failed step that stops --apply."""
    monkeypatch.setattr(b2y, "GENERIC_IMAGES", (b2y._gh("ioc-generic"),))

    def unreadable(repo):
        raise OSError("rate limited")

    monkeypatch.setattr(b2y, "_github_release", unreadable)
    monkeypatch.setattr(b2y, "latest_tag", lambda url: "2.0")
    monkeypatch.setattr(b2y, "image_entity_types", lambda ref: BASE)
    b2y.candidates.cache_clear()
    try:
        (got,) = b2y.candidates()
    finally:
        b2y.candidates.cache_clear()
    assert got.ref == "ghcr.io/epics-containers/ioc-generic-runtime:2.0"
    assert got.types == BASE
    assert got.failed and "used its highest tag 2.0" in got.problem


class FakeIndex:
    failures: dict[str, str] = {}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A services repo with an .ioc_template, offline pattern and image lookups,
    and the sample XML as the beamline's only IOC."""
    services = tmp_path / "services"
    template = services / ".ioc_template"
    (template / "config").mkdir(parents=True)
    (template / "config" / "ioc.yaml").write_text("entities: []\n")
    (template / "values.yaml").write_text(
        "# yaml-language-server: $schema=x\n\nioc-instance:\n"
        "  image: REPLACE_WITH_IMAGE_URI\n"
    )
    monkeypatch.setattr(b2y, "discover_xmls", lambda _b: ([XML], XML.parent, "work"))
    monkeypatch.setattr(b2y, "pattern_index", FakeIndex)
    monkeypatch.setattr(b2y, "plan_patterns", lambda e, r: PatternPlan())
    monkeypatch.setattr(b2y, "runtime_image", lambda: (RUNTIME, ""))
    monkeypatch.setattr(b2y, "image_entity_types", lambda image: BASE)
    big = b2y.Candidate(b2y.GenericImage("org/ioc-all", "ghcr.io/org/ioc-all"), ALL)

    def all_types():
        # one image that builds every type the sample IOC uses
        builder = b2y.Builder()
        builder.load(XML)
        ioc = b2y.dispatch(builder, XML)
        big.types = frozenset(str(e["type"]) for e in ioc.entities)
        return (big,)

    monkeypatch.setattr(b2y, "candidates", all_types)
    return tmp_path


def _init(tmp_path: Path, ioc: str) -> dict:
    init = tmp_path / "init" / "srv01"
    init.mkdir(parents=True)
    (init / "soft-iocs").write_text(f"{ioc} 7001\n")
    table = tmp_path / "redirect_table"
    table.write_text(
        f"{ioc} /dls_sw/prod/R3.14.12.7/ioc/X/{ioc}/1-0/bin/linux-x86_64/st.sh\n"
    )
    return {"init_dir": tmp_path / "init", "redirect_table": table}


def _legacy(repo: Path) -> Path:
    folder = repo / "services" / XML.stem.lower()
    folder.mkdir()
    (folder / "values.yaml").write_text("dev-c7:\n  iocVersion: 1-0\n")
    return folder


def test_plan_actions_by_folder_kind(repo: Path):
    plan = b2y.build_plan("BL11I", repo, **_init(repo, XML.stem))
    (entry,) = plan.entries
    assert entry.action == "add"
    assert entry.image == ALL
    assert entry.live == "live on srv01"
    assert "still runs on srv01" in entry.header
    assert plan.failures == []

    folder = _legacy(repo)
    assert b2y.build_plan("BL11I", repo).entries[0].action == "replace"

    (folder / "values.yaml").write_text("ioc-instance: {}\n")
    (folder / "config").mkdir()
    (folder / "config" / "ioc.yaml").write_text("entities: []\n")
    entry = b2y.build_plan("BL11I", repo).entries[0]
    assert (entry.action, entry.reason) == ("skip", "ibek folder: use reconvert")

    (folder / "config" / "ioc.yaml").unlink()
    assert b2y.build_plan("BL11I", repo).entries[0].action == "skip"


def test_plan_reports_retired_and_filters(repo: Path):
    kw = _init(repo, "OTHER")
    (repo / "redirect_table").write_text(f"{XML.stem} /dls_sw/prod/x/bin/x/st.sh\n")
    entry = b2y.build_plan("BL11I", repo, **kw).entries[0]
    assert entry.live.startswith("not live: retired")
    assert not entry.header
    assert b2y.build_plan("BL11I", repo, only=["nope"]).entries == []


def _fake_convert(converted: list | None = None, result: ConvertResult | None = None):
    def convert(xml, yaml, schema, description="", image=None, image_types=None):
        if converted is not None:
            converted.append((xml, yaml, description, image))
        yaml.write_text("entities: []\n")
        return result or ConvertResult()

    return convert


def test_apply_replaces_a_legacy_folder(repo: Path, monkeypatch):
    folder = _legacy(repo)
    (folder / "stale").write_text("x")
    converted: list = []
    monkeypatch.setattr(b2y, "convert_file", _fake_convert(converted))
    plan = b2y.build_plan("BL11I", repo, **_init(repo, XML.stem))
    b2y.apply_plan(plan, {folder.name: "Test IOC"}, validate=False)

    assert not (folder / "stale").exists()
    assert not list((repo / "services").glob(".*backup"))
    values = (folder / "values.yaml").read_text()
    assert values.startswith("# yaml-language-server")
    assert "# WARNING: this IOC still runs on srv01" in values
    # the image goes to xml2yaml, which sets it in values.yaml
    assert converted == [(XML, folder / "config" / "ioc.yaml", "Test IOC", ALL)]
    assert plan.entries[0].status == "ok"


def test_apply_puts_the_legacy_folder_back_when_conversion_fails(
    repo: Path, monkeypatch
):
    folder = _legacy(repo)
    (folder / "keep").write_text("x")

    def fail(xml, yaml, schema, description="", image=None, image_types=None):
        yaml.write_text("half written\n")
        raise RuntimeError("converter crashed")

    monkeypatch.setattr(b2y, "convert_file", fail)
    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan, validate=False)

    (entry,) = plan.entries
    assert entry.status == "error"
    assert (
        "converter crashed; the dev-c7 legacy folder is put back"
        in (entry.warnings[-1])
    )
    assert (folder / "keep").read_text() == "x"
    assert (folder / "values.yaml").read_text() == "dev-c7:\n  iocVersion: 1-0\n"
    assert not (folder / "config").exists()
    assert not list((repo / "services").glob(".*backup"))


def test_apply_removes_an_added_folder_when_conversion_fails(repo: Path, monkeypatch):
    def fail(xml, yaml, schema, description="", image=None, image_types=None):
        raise RuntimeError("converter crashed")

    monkeypatch.setattr(b2y, "convert_file", fail)
    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan, validate=False)

    assert plan.entries[0].status == "error"
    assert not (repo / "services" / XML.stem.lower()).exists()


def test_apply_refuses_a_folder_that_changed(repo: Path):
    folder = _legacy(repo)
    plan = b2y.build_plan("BL11I", repo)
    (folder / "values.yaml").write_text("ioc-instance: {}\n")
    b2y.apply_plan(plan, validate=False)
    assert plan.entries[0].status == "error"
    assert "no longer a dev-c7 legacy folder" in plan.entries[0].warnings[-1]
    assert (folder / "values.yaml").read_text() == "ioc-instance: {}\n"


@pytest.mark.parametrize(
    "failure",
    ["index", "runtime", "candidate", "no-schema"],
)
def test_a_failed_step_stops_apply(repo: Path, monkeypatch, capsys, failure: str):
    folder = _legacy(repo)
    if failure == "index":
        monkeypatch.setattr(
            FakeIndex, "failures", {SUPPORT_LIBRARY: "cannot clone"}, raising=False
        )
    elif failure == "runtime":
        monkeypatch.setattr(b2y, "runtime_image", lambda: (RUNTIME, "rate limited"))
    else:
        generic = b2y.GenericImage("org/ioc-x", "ghcr.io/org/ioc-x")
        bad = b2y.Candidate(
            generic, problem="unreachable", failed=failure == "candidate"
        )
        monkeypatch.setattr(b2y, "candidates", lambda: (bad,))

    code = b2y.beamline2yaml_cli("BL11I", repo, apply=True, validate=False)

    captured = capsys.readouterr()
    assert code == 1
    assert "not applied, as a step of the plan failed" in captured.err
    assert "failed steps" in captured.out
    assert (folder / "values.yaml").read_text() == "dev-c7:\n  iocVersion: 1-0\n"


def test_unresolved_modules_block_and_keep_the_legacy_folder(repo: Path, monkeypatch):
    folder = _legacy(repo)
    # no generic IOC builds hidenRGA
    narrow = b2y.Candidate(
        b2y.GenericImage("org/ioc-narrow", "ghcr.io/org/ioc-narrow"),
        "ghcr.io/org/ioc-narrow:1",
        BASE,
    )
    monkeypatch.setattr(b2y, "candidates", lambda: (narrow,))
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())

    plan = b2y.build_plan("BL11I", repo)
    (entry,) = plan.entries
    assert entry.action == "blocked"
    assert entry.reason.startswith("no generic IOC image (")
    assert entry.reason.endswith("; dev-c7 legacy folder kept")
    b2y.apply_plan(plan, validate=False)
    assert entry.status == ""
    assert (folder / "values.yaml").read_text() == "dev-c7:\n  iocVersion: 1-0\n"


def test_unresolved_module_blocks_an_add(repo: Path, monkeypatch):
    """A module the chosen image does not build, here a beamline module whose
    pattern rejects its entities, blocks the IOC: no folder is written."""
    rejected = PatternPlan(build_time={"hidenRGA": "rejects 0.P"})
    monkeypatch.setattr(b2y, "plan_patterns", lambda e, r: rejected)
    monkeypatch.setattr(
        b2y,
        "classify_modules",
        lambda *a: [ModuleStatus("hidenRGA", "unresolved", "rejects 0.P")],
    )
    plan = b2y.build_plan("BL11I", repo)
    (entry,) = plan.entries
    assert (entry.action, entry.reason) == ("blocked", "unresolved modules hidenRGA")
    b2y.apply_plan(plan, validate=False)
    assert not (repo / "services" / XML.stem.lower()).exists()


def test_non_linux_xml_is_blocked(repo: Path, monkeypatch, tmp_path: Path):
    xml = tmp_path / XML.name
    xml.write_text(XML.read_text().replace("linux-x86_64", "windows-x64"))
    monkeypatch.setattr(b2y, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))

    (entry,) = b2y.build_plan("BL11I", repo).entries

    assert entry.action == "blocked"
    assert entry.reason == "windows-x64 IOC, not runnable in a Linux container"


def test_windows_boot_script_is_blocked(repo: Path):
    table = repo / "redirect_table"
    table.write_text(f"{XML.stem} /dls_sw/prod/x/bin/windows-x64/st.bat\n")

    (entry,) = b2y.build_plan("BL11I", repo, redirect_table=table).entries

    assert entry.action == "blocked"
    assert entry.reason.startswith("Windows IOC")


def test_apply_fastcs_converts_in_place(repo: Path, monkeypatch):
    """A dedicated PandA IOC gets no folder from the template: xml2yaml writes
    the fastcs instance, and its values.yaml gets the live warning."""
    folder = repo / "services" / XML.stem.lower()
    converted: list = []

    def fastcs(xml, yaml, schema, description="", image=None, image_types=None):
        converted.append(image)
        folder.mkdir()
        (folder / "values.yaml").write_text("fastcs: {}\n")
        return ConvertResult(ioc_yaml_written=False, notes=["fastcs written"])

    monkeypatch.setattr(b2y, "convert_file", fastcs)
    entry = b2y.Entry(XML.stem, str(XML), folder.name, "fastcs", header="WARNING: x.")
    plan = b2y.Plan("BL11I", str(repo), str(XML.parent), "work", [entry])

    b2y.apply_plan(plan, validate=False)

    assert converted == [None]
    assert entry.status == "fastcs"
    assert entry.notes == ["fastcs written"]
    assert (folder / "values.yaml").read_text() == "# WARNING: x.\nfastcs: {}\n"


def test_warnings_appear_once(repo: Path, monkeypatch):
    """The conversion repeats the plan's warnings; each is kept once."""
    plan = b2y.build_plan("BL11I", repo)
    (entry,) = plan.entries
    entry.warnings = ["shared warning"]
    result = ConvertResult(warnings=["shared warning", "new"], notes=["n"])
    monkeypatch.setattr(b2y, "convert_file", _fake_convert(result=result))

    b2y.apply_plan(plan, validate=False)

    assert entry.warnings == ["shared warning", "new"]
    assert entry.notes == ["n"]


def test_cli_dry_run_writes_nothing(repo: Path, capsys):
    code = b2y.beamline2yaml_cli("BL11I", repo, **_init(repo, XML.stem))
    out = capsys.readouterr().out
    assert code == 0
    assert "dry run" in out and XML.stem in out
    assert not (repo / "services" / XML.stem.lower()).exists()


def test_status_shows_schema_and_what_still_blocks():
    entry = b2y.Entry("X", "x.xml", "x", "add", status="ok", schema="ok")
    entry.modules = [ModuleStatus("m", "unresolved", "r")]
    assert b2y._status(entry) == "[ok; schema ok; no image; unresolved m]"


def test_plan_reports_modules(repo: Path, monkeypatch, capsys):
    """A pattern the chosen image installs is build-time and not added."""
    hiden = pattern("hidenRGA")
    monkeypatch.setattr(b2y, "plan_patterns", lambda e, r: PatternPlan([hiden]))

    code = b2y.beamline2yaml_cli("BL11I", repo, json_out=True)

    (entry,) = json.loads(capsys.readouterr().out)["entries"]
    assert code == 0
    assert entry["patterns"] == []
    kinds = {m["module"]: (m["kind"], m["reason"]) for m in entry["modules"]}
    assert kinds["hidenRGA"] == ("build-time", f"{ALL} installs it")
    assert kinds["asyn"] == ("build-time", "")

    b2y.beamline2yaml_cli("BL11I", repo)
    out = capsys.readouterr().out
    assert "modules:\n  BL11I-CS-IOC-09: build-time: epics, devIocStats" in out


def test_apply_takes_the_conversion_module_report(repo: Path, monkeypatch):
    modules = [
        ModuleStatus("asyn", "build-time"),
        ModuleStatus("x", "unresolved", "no generic model"),
    ]
    warning = "unresolved module x, nothing can run it: no generic model"
    result = ConvertResult(
        warnings=[warning], notes=["build-time modules: asyn", "other"], modules=modules
    )
    monkeypatch.setattr(b2y, "convert_file", _fake_convert(result=result))
    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan, validate=False)

    (entry,) = plan.entries
    assert entry.modules == modules
    # the module notes are rendered from entry.modules
    assert entry.notes == ["other"]
    assert entry.warnings == [warning]
