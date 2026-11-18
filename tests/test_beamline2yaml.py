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
from builder2ibek.vendor_patterns import ModuleStatus, SchemaUnavailableError
from tests.conftest import requires_support

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
    monkeypatch.setattr(b2y, "fetch_entity_types", lambda ref: BASE)
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
    patterns: dict[str, Pattern] = {}


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
    monkeypatch.setattr(b2y, "fetch_entity_types", lambda image: BASE)
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
    assert "converter crashed; the previous folder is put back" in (entry.warnings[-1])
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
    [
        "index",
        "runtime",
        "runtime-schema",
        "candidate",
        "no-schema",
        "leftover-backup",
    ],
)
def test_a_failed_step_stops_apply(repo: Path, monkeypatch, capsys, failure: str):
    folder = _legacy(repo)
    if failure == "index":
        monkeypatch.setattr(
            FakeIndex, "failures", {SUPPORT_LIBRARY: "cannot clone"}, raising=False
        )
    elif failure == "runtime":
        monkeypatch.setattr(b2y, "runtime_image", lambda: (RUNTIME, "rate limited"))
    elif failure == "runtime-schema":

        def timed_out(image):
            raise SchemaUnavailableError(f"cannot fetch the ioc schema of {image}")

        monkeypatch.setattr(b2y, "fetch_entity_types", timed_out)
    elif failure == "leftover-backup":
        b2y.backup_path(repo / "services", folder.name).mkdir()
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


class Release:
    """A library release faked for library_release."""

    def __init__(self, library: str, tag: str):
        models = {
            # a model added after 0.8.1 is not installed by an image pinning it
            "EdwardsScroll": {"Scroll"} if tag == "0.8.1" else {"Scroll", "New"},
            "QPC": {"QPC"},
        }
        self.patterns = {
            m: Pattern(library, m, tag, frozenset(names), XML)
            for m, names in models.items()
        }


def test_gitlab_candidate_adds_the_patterns_it_installs(monkeypatch):
    """ibek pattern install in the Dockerfile, from a --list file or on the
    line, also across line continuations, installs patterns whose types, at the
    release each pins, the image then has."""
    dockerfile = (
        "RUN ansible.sh asyn\n"
        "COPY runtime-patterns.txt runtime-patterns.txt\n"
        "RUN ibek pattern install --list=runtime-patterns.txt\n"
        "RUN ibek pattern install \\\n"
        "    ibek-runtime-streamdevice:QPC@0.8.1 --frobnicate \\\n"
        "    && echo done\n"
    )
    listed = (
        "# patterns this image installs\n"
        "ibek-runtime-streamdevice:EdwardsScroll@0.8.1\n"
        "ibek-runtime-streamdevice:NotIndexed@0.8.1  # no such pattern\n"
        "QPC@0.8.1\n"
        "elsewhere:QPC@0.8.1\n"
    )

    def get(host, path):
        if "releases" in path:
            return json.dumps({"tag_name": "2026.1.1"}).encode()
        if "runtime-patterns.txt" in path:
            assert "ref=2026.1.1" in path
            return listed.encode()
        return dockerfile.encode()

    monkeypatch.setattr(b2y, "_gitlab_get", get)
    monkeypatch.setattr(b2y, "library_release", Release)
    monkeypatch.setattr(b2y, "support_models", lambda: {})
    generic = b2y.GenericImage("g/ioc-vac", "reg/ioc-vac", gitlab="gitlab.example")

    got = b2y._gitlab_candidate(generic, BASE)

    assert got.types == BASE | {"EdwardsScroll.Scroll", "QPC.QPC"}
    assert [(p.module, p.version) for p in got.installed] == [
        ("EdwardsScroll", "0.8.1"),
        ("QPC", "0.8.1"),
    ]
    assert not got.failed
    assert got.warnings == [
        "ibek pattern install: unknown option --frobnicate",
        "installed pattern ibek-runtime-streamdevice:NotIndexed@0.8.1: "
        "ibek-runtime-streamdevice 0.8.1 has no pattern NotIndexed, not matched",
        "installed pattern 'QPC@0.8.1' is not library:module@version: not matched",
        "installed pattern elsewhere:QPC@0.8.1: unknown library elsewhere, not matched",
    ]


def test_plan_lists_the_image_warnings(repo: Path, monkeypatch, capsys):
    cand = b2y.Candidate(
        b2y.GenericImage("org/ioc-all", "ghcr.io/org/ioc-all"),
        ALL,
        frozenset(),
        warnings=["installed pattern x: not matched"],
    )
    monkeypatch.setattr(b2y, "candidates", lambda: (cand,))
    b2y.beamline2yaml_cli("BL11I", repo)
    out = capsys.readouterr().out
    assert f"generic IOC warnings:\n  {ALL}: installed pattern x: not matched" in out


def test_gitlab_candidate_fails_without_the_pattern_library(monkeypatch):
    def get(host, path):
        if "releases" in path:
            return json.dumps({"tag_name": "1"}).encode()
        if path.endswith("ref=1") and "Dockerfile" in path:
            return b"RUN ibek pattern install ibek-runtime-streamdevice:QPC@0.8.1\n"
        raise AssertionError(path)

    def no_clone(library, tag):
        raise OSError("clone timed out")

    monkeypatch.setattr(b2y, "_gitlab_get", get)
    monkeypatch.setattr(b2y, "library_release", no_clone)
    generic = b2y.GenericImage("g/ioc-vac", "reg/ioc-vac", gitlab="gitlab.example")

    got = b2y._gitlab_candidate(generic, BASE)

    assert got.failed and "clone timed out" in got.problem


def test_xml2yaml_image_types_of_a_gitlab_candidate(monkeypatch):
    """xml2yaml --image matches a GitLab generic IOC as beamline2yaml does,
    at the tag it names."""
    vac = next(g for g in b2y.GENERIC_IMAGES if g.gitlab)
    seen = []

    def gitlab(generic, base, tag=None):
        seen.append((generic, base, tag))
        return b2y.Candidate(generic, f"{generic.image}:{tag}", base | {"x.y"})

    monkeypatch.setattr(b2y, "_gitlab_candidate", gitlab)
    monkeypatch.setattr(b2y, "_github_release", lambda repo: "1.0")
    monkeypatch.setattr(b2y, "fetch_entity_types", lambda image: BASE)

    types, problem = b2y.gitlab_image_types(f"{vac.image}:2026.11.4")

    assert (types, problem) == (BASE | {"x.y"}, "")
    assert seen == [(vac, BASE, "2026.11.4")]
    assert b2y.gitlab_image_types("ghcr.io/org/ioc-pmac:1") == (None, "")


def test_unfetchable_schema_is_a_failure_not_a_missing_one(monkeypatch):
    monkeypatch.setattr(b2y, "_github_release", lambda repo: "1.0")
    generic = b2y._gh("ioc-generic")

    def timed_out(image):
        raise SchemaUnavailableError("timed out")

    monkeypatch.setattr(b2y, "fetch_entity_types", timed_out)
    got = b2y._github_candidate(generic)
    assert got.failed and got.problem == "timed out"

    monkeypatch.setattr(b2y, "fetch_entity_types", lambda image: None)
    got = b2y._github_candidate(generic)
    assert not got.failed and got.problem.startswith("no published ioc schema")


def test_blocked_ioc_modules_are_classified_against_the_closest(
    repo: Path, monkeypatch
):
    narrow = b2y.Candidate(
        b2y.GenericImage("org/ioc-narrow", "ghcr.io/org/ioc-narrow"),
        "ghcr.io/org/ioc-narrow:1",
        BASE,
    )
    monkeypatch.setattr(b2y, "candidates", lambda: (narrow,))

    (entry,) = b2y.build_plan("BL11I", repo).entries

    kinds = {m.module: (m.kind, m.reason) for m in entry.modules}
    assert kinds["asyn"] == ("build-time", "")
    assert kinds["hidenRGA"] == (
        "unresolved",
        "ghcr.io/org/ioc-narrow:1 does not build hidenRGA.hidenRGA_qga",
    )


LEGACY = "dev-c7:\n  iocVersion: 1-0\n"


def _assert_legacy_back(repo: Path, folder: Path):
    assert (folder / "keep").read_text() == "x"
    assert (folder / "values.yaml").read_text() == LEGACY
    assert not (folder / "config").exists()
    assert not list((repo / "services").glob(".*backup"))


@pytest.mark.parametrize(
    "result",
    [
        ConvertResult(
            warnings=["ibek pattern add X failed: boom"],
            pattern_errors=["ibek pattern add X failed: boom"],
        ),
        ConvertResult(ioc_yaml_written=False),
    ],
    ids=["pattern-add-failed", "no-ioc-yaml"],
)
def test_incomplete_conversion_puts_the_legacy_folder_back(
    repo: Path, monkeypatch, result: ConvertResult
):
    folder = _legacy(repo)
    (folder / "keep").write_text("x")
    monkeypatch.setattr(b2y, "convert_file", _fake_convert(result=result))

    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan, validate=False)

    assert plan.entries[0].status == "error"
    assert "the previous folder is put back" in plan.entries[0].warnings[-1]
    _assert_legacy_back(repo, folder)


def test_schema_failure_puts_the_legacy_folder_back(repo: Path, monkeypatch):
    folder = _legacy(repo)
    (folder / "keep").write_text("x")
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(
        b2y,
        "validate_configs",
        lambda configs, support_yamls: [
            {"ioc_name": n, "status": "fail", "stderr": "bad"} for n in configs
        ],
    )

    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan)

    (entry,) = plan.entries
    assert (entry.status, entry.schema) == ("error", "fail")
    _assert_legacy_back(repo, folder)


def test_schema_pass_removes_the_backup(repo: Path, monkeypatch):
    folder = _legacy(repo)
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(
        b2y,
        "validate_configs",
        lambda configs, support_yamls: [
            {"ioc_name": n, "status": "ok"} for n in configs
        ],
    )

    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan)

    assert (plan.entries[0].status, plan.entries[0].schema) == ("ok", "ok")
    assert (folder / "config" / "ioc.yaml").is_file()
    assert not list((repo / "services").glob(".*backup"))


@pytest.mark.parametrize("when", ["converting", "validating"])
def test_interrupt_puts_the_legacy_folder_back(repo: Path, monkeypatch, when: str):
    folder = _legacy(repo)
    (folder / "keep").write_text("x")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    if when == "converting":
        monkeypatch.setattr(b2y, "convert_file", interrupt)
    else:
        monkeypatch.setattr(b2y, "convert_file", _fake_convert())
        monkeypatch.setattr(b2y, "validate_configs", interrupt)

    plan = b2y.build_plan("BL11I", repo)
    with pytest.raises(KeyboardInterrupt):
        b2y.apply_plan(plan)

    _assert_legacy_back(repo, folder)


def test_fastcs_on_a_legacy_folder_is_put_back_on_failure(repo: Path, monkeypatch):
    """xml2yaml replaces a legacy folder with the fastcs instance; a copy is
    kept until it has."""
    folder = _legacy(repo)
    (folder / "keep").write_text("x")

    def fail(xml, yaml, schema, description="", image=None, image_types=None):
        import shutil

        shutil.rmtree(folder)
        folder.mkdir()
        (folder / "half").write_text("written")
        raise RuntimeError("fastcs write failed")

    monkeypatch.setattr(b2y, "convert_file", fail)
    entry = b2y.Entry(XML.stem, str(XML), folder.name, "fastcs")
    plan = b2y.Plan("BL11I", str(repo), str(XML.parent), "work", [entry])

    b2y.apply_plan(plan, validate=False)

    assert entry.status == "error"
    assert not (folder / "half").exists()
    _assert_legacy_back(repo, folder)


def test_fastcs_on_a_legacy_folder_drops_the_copy_on_success(repo: Path, monkeypatch):
    folder = _legacy(repo)

    def fastcs(xml, yaml, schema, description="", image=None, image_types=None):
        (folder / "values.yaml").write_text("fastcs: {}\n")
        return ConvertResult(ioc_yaml_written=False)

    monkeypatch.setattr(b2y, "convert_file", fastcs)
    entry = b2y.Entry(XML.stem, str(XML), folder.name, "fastcs")
    plan = b2y.Plan("BL11I", str(repo), str(XML.parent), "work", [entry])

    b2y.apply_plan(plan, validate=False)

    assert entry.status == "fastcs"
    assert (folder / "values.yaml").read_text() == "fastcs: {}\n"
    assert not list((repo / "services").glob(".*backup"))


MIXED_XML = """\
<?xml version="1.0" ?>
<components arch="linux-x86_64">
\t<asyn.AsynIP name="VA_TSERV1_1" port="127.0.0.1:4001"/>
\t<asyn.AsynIP name="VA_TSERV1_8" port="127.0.0.1:4008"/>
\t<asyn.AsynIP name="VA_TSERV1_12" port="127.0.0.1:4012"/>
\t<digitelMpc.digitelMpc device="BL08J-VA-MPC-01" name="MPC1" port="VA_TSERV1_1"/>
\t<EdwardsScroll.EdwardsScroll P="BL08J-VA-SCROL-01" name="SCROLL1" port="VA_TSERV1_8"/>
\t<EdwardsNextTurbo.EdwardsNextTurbo P="BL08J-VA-TURBO-01" name="TURBO1"
\t\tport="VA_TSERV1_12"/>
</components>
"""


def test_mixed_vacuum_ioc(repo: Path, monkeypatch, tmp_path: Path):
    """A trimmed BL08J-VA-IOC-02, planned with the pinned pattern libraries:
    a vacuum image that builds digitelMpc and installs EdwardsScroll, so only
    EdwardsNextTurbo is added as a pattern."""
    from builder2ibek import vendor_patterns

    xml = tmp_path / "BL08J-VA-IOC-02.xml"
    xml.write_text(MIXED_XML)
    monkeypatch.setattr(b2y, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    monkeypatch.setattr(b2y, "plan_patterns", vendor_patterns.plan_patterns)
    monkeypatch.setattr(b2y, "pattern_index", vendor_patterns.pattern_index)

    builder = b2y.Builder()
    builder.load(xml)
    types = {str(e["type"]) for e in b2y.dispatch(builder, xml).entities}
    vac = b2y.Candidate(
        b2y.GenericImage("org/ioc-vac", "ghcr.io/org/ioc-vac", streamdevice=True),
        "ghcr.io/org/ioc-vac:1",
        frozenset(t for t in types if not t.startswith("EdwardsNextTurbo.")),
    )
    generic = b2y.Candidate(
        b2y.GenericImage("org/ioc-generic", "ghcr.io/org/ioc-generic"),
        "ghcr.io/org/ioc-generic:1",
        BASE,
    )
    monkeypatch.setattr(b2y, "candidates", lambda: (generic, vac))

    (entry,) = b2y.build_plan("BL08J", repo).entries

    assert entry.action == "add"
    assert entry.image == "ghcr.io/org/ioc-vac:1"
    assert [p.partition("@")[0] for p in entry.patterns] == [
        "ibek-runtime-streamdevice:EdwardsNextTurbo"
    ]
    kinds = {m.module: (m.kind, m.reason) for m in entry.modules}
    assert kinds["EdwardsNextTurbo"] == ("pattern", "")
    assert kinds["EdwardsScroll"] == ("build-time", "ghcr.io/org/ioc-vac:1 installs it")
    assert kinds["digitelMpc"][0] == "build-time"
    assert not [m for m in entry.modules if m.kind == "unresolved"]


def _schema_fails(configs, support_yamls):
    return [{"ioc_name": n, "status": "fail", "stderr": "bad"} for n in configs]


def test_schema_failure_removes_an_added_folder(repo: Path, monkeypatch):
    """Nothing that failed stays written: a re-run plans the IOC as an add
    again, not as an ibek folder to reconvert."""
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(b2y, "validate_configs", _schema_fails)

    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan)

    (entry,) = plan.entries
    assert (entry.status, entry.schema) == ("error", "fail")
    assert entry.warnings[-1] == "schema validation failed: its folder is removed"
    assert not (repo / "services" / XML.stem.lower()).exists()
    assert b2y.build_plan("BL11I", repo).entries[0].action == "add"


@pytest.mark.parametrize("when", ["converting", "validating"])
def test_interrupt_removes_an_added_folder(repo: Path, monkeypatch, when: str):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    if when == "converting":

        def convert(xml, yaml, *args, **kwargs):
            yaml.write_text("half written\n")
            raise KeyboardInterrupt

        monkeypatch.setattr(b2y, "convert_file", convert)
    else:
        monkeypatch.setattr(b2y, "convert_file", _fake_convert())
        monkeypatch.setattr(b2y, "validate_configs", interrupt)

    plan = b2y.build_plan("BL11I", repo)
    with pytest.raises(KeyboardInterrupt):
        b2y.apply_plan(plan)

    assert sorted(p.name for p in (repo / "services").iterdir()) == [".ioc_template"]


def _with_siblings(services: Path, result: ConvertResult | None = None):
    """A conversion that writes two fastcs-pandablocks instances beside the
    IOC, one of which was already there, then fails, or returns ``result``."""

    def convert(xml, yaml, *args, **kwargs):
        for name in ("bl11i-panda-01", "bl11i-panda-02"):
            (services / name / "config").mkdir(parents=True, exist_ok=True)
            (services / name / "config" / "controller.yaml").write_text("new\n")
        yaml.write_text("entities: []\n")
        if result is None:
            raise RuntimeError("pattern step crashed")
        return result

    return convert


@pytest.mark.parametrize("fails", ["converting", "validating"])
def test_failure_removes_the_fastcs_siblings_it_created(
    repo: Path, monkeypatch, fails: str
):
    services = repo / "services"
    existing = services / "bl11i-panda-02" / "config"
    existing.mkdir(parents=True)
    (existing / "controller.yaml").write_text("old\n")
    result = None if fails == "converting" else ConvertResult()
    monkeypatch.setattr(b2y, "convert_file", _with_siblings(services, result))
    monkeypatch.setattr(b2y, "validate_configs", _schema_fails)

    plan = b2y.build_plan("BL11I", repo)
    b2y.apply_plan(plan)

    assert plan.entries[0].status == "error"
    assert not (services / "bl11i-panda-01").exists()
    # one that was there before is never touched, even when rewritten
    assert (existing / "controller.yaml").read_text() == "new\n"
    assert not (services / XML.stem.lower()).exists()


def test_every_undo_is_attempted(tmp_path: Path):
    """An undo that fails does not stop the others."""
    broken = b2y._Written(tmp_path / "a", tmp_path / ".a.backup")
    (tmp_path / "a").mkdir()
    folder = tmp_path / "b"
    (folder / "new").mkdir(parents=True)
    (tmp_path / ".b.backup").mkdir()
    (tmp_path / ".b.backup" / "keep").write_text("x")
    good = b2y._Written(folder, tmp_path / ".b.backup")

    errors = b2y._undo_all([broken, good])

    assert len(errors) == 1 and "cannot put" in errors[0]
    assert (folder / "keep").read_text() == "x"
    assert not (folder / "new").exists()


def test_an_interrupt_undoes_every_ioc_whatever_one_raises(
    repo: Path, monkeypatch, capsys
):
    """The legacy folder is put back although an earlier undo failed."""
    folder = _legacy(repo)
    (folder / "keep").write_text("x")
    services = repo / "services"
    broken = b2y._Written(services / "gone", services / ".gone.backup")
    real_apply = b2y._apply_entry
    applied: list = []

    def apply_entry(services, entry, descriptions, written):
        applied.append(entry.ioc)
        if len(applied) == 1:
            written[entry.ioc] = broken
            return
        real_apply(services, entry, descriptions, written)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(b2y, "_apply_entry", apply_entry)
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(b2y, "validate_configs", interrupt)
    plan = b2y.build_plan("BL11I", repo)
    plan.entries.insert(0, b2y.Entry("GONE", str(XML), "gone", "add"))

    with pytest.raises(KeyboardInterrupt) as raised:
        b2y.apply_plan(plan)

    assert any("cannot put" in note for note in raised.value.__notes__)
    assert "cannot put" in capsys.readouterr().err
    _assert_legacy_back(repo, folder)


VAC_XML = """\
<?xml version="1.0" ?>
<components arch="linux-x86_64">
\t<asyn.AsynIP name="VA_TSERV1_8" port="127.0.0.1:4008"/>
\t<asyn.AsynIP name="VA_TSERV1_12" port="127.0.0.1:4012"/>
\t<EdwardsScroll.EdwardsScroll P="BL08J-VA-SCROL-01" name="SCROLL1" port="VA_TSERV1_8"/>
\t<EdwardsNextTurbo.EdwardsNextTurbo P="BL08J-VA-TURBO-01" name="TURBO1"
\t\tport="VA_TSERV1_12"/>
</components>
"""


@requires_support
def test_apply_validates_with_the_patterns_the_image_installs(
    repo: Path, monkeypatch, tmp_path: Path
):
    """A vacuum IOC on an image that installs its Edwards patterns: nothing is
    vendored, and the schema check has the image's support YAMLs, at the
    release it pins, besides this checkout's."""
    from builder2ibek import vendor_patterns
    from tests.pattern_pins import PATTERN_TAG

    xml = tmp_path / "BL08J-VA-IOC-02.xml"
    xml.write_text(VAC_XML)
    monkeypatch.setattr(b2y, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    monkeypatch.setattr(b2y, "plan_patterns", vendor_patterns.plan_patterns)
    monkeypatch.setattr(b2y, "pattern_index", vendor_patterns.pattern_index)
    # not pattern-only: the runtime image builds no asyn
    monkeypatch.setattr(b2y, "image_entity_types", lambda image: frozenset())
    release = b2y.library_release(STREAMDEVICE_LIBRARY, PATTERN_TAG)
    installed = tuple(
        release.patterns[m] for m in ("EdwardsNextTurbo", "EdwardsScroll")
    )
    builder = b2y.Builder()
    builder.load(xml)
    types = {str(e["type"]) for e in b2y.dispatch(builder, xml).entities}
    vac = b2y.Candidate(
        b2y.GenericImage("org/ioc-vac", "ghcr.io/org/ioc-vac", streamdevice=True),
        "ghcr.io/org/ioc-vac:1",
        frozenset(types) | b2y._pattern_types(installed),
        installed=installed,
    )
    monkeypatch.setattr(b2y, "candidates", lambda: (vac,))

    plan = b2y.build_plan("BL08J", repo)
    b2y.apply_plan(plan)

    (entry,) = plan.entries
    assert (entry.status, entry.schema) == ("ok", "ok"), entry.schema_error
    assert entry.patterns == []
    config = repo / "services" / "bl08j-va-ioc-02" / "config"
    assert not list(config.glob("*.ibek.support.yaml"))
    assert not (config.parent / "runtime-lock.yaml").exists()


def test_only_new_fastcs_instances_are_siblings(tmp_path: Path):
    """Never another run's backup, nor a new folder that is no fastcs
    instance."""
    before: set[str] = set()
    for name in ("panda", ".x.beamline2yaml-backup", "other", "ioc"):
        (tmp_path / name / "config").mkdir(parents=True)
    for name in ("panda", ".x.beamline2yaml-backup", "ioc"):
        (tmp_path / name / "config" / "controller.yaml").write_text("x\n")
    assert b2y._created(tmp_path, before, "ioc") == [tmp_path / "panda"]


def test_undo_all_undoes_the_last_written_first(monkeypatch, tmp_path: Path):
    order: list = []

    def undo(written):
        order.append(written.folder.name)
        return []

    monkeypatch.setattr(b2y, "_undo", undo)
    b2y._undo_all([b2y._Written(tmp_path / "a"), b2y._Written(tmp_path / "b")])
    assert order == ["b", "a"]


def test_an_interrupted_schema_failure_undo_is_finished(repo: Path, monkeypatch):
    """Ctrl-C during the undo of a schema failure: the IOC is still on the
    undo list, so the legacy folder is put back."""
    folder = _legacy(repo)
    (folder / "keep").write_text("x")
    real_undo = b2y._undo
    calls: list = []

    def undo(written):
        calls.append(written)
        if len(calls) == 1:
            # cut short after removing the new folder
            import shutil

            shutil.rmtree(written.folder)
            written.new = False
            raise KeyboardInterrupt
        return real_undo(written)

    monkeypatch.setattr(b2y, "_undo", undo)
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(b2y, "validate_configs", _schema_fails)

    with pytest.raises(KeyboardInterrupt):
        b2y.apply_plan(b2y.build_plan("BL11I", repo))

    assert len(calls) == 2
    _assert_legacy_back(repo, folder)


def test_undo_twice_never_removes_a_folder_put_back(repo: Path):
    folder = _legacy(repo)
    (folder / "keep").write_text("x")
    services = repo / "services"
    backup = b2y._move_aside(services, folder.name)
    folder.mkdir()
    written = b2y._Written(folder, backup)

    assert b2y._undo(written) == []
    assert b2y._undo(written) == []
    _assert_legacy_back(repo, folder)


def test_an_interrupt_after_converting_undoes_the_ioc(repo: Path, monkeypatch):
    """Ctrl-C in the tail of _apply_entry, after the conversion returned."""
    folder = _legacy(repo)
    (folder / "keep").write_text("x")

    def interrupt(statuses):
        raise KeyboardInterrupt

    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    plan = b2y.build_plan("BL11I", repo)
    monkeypatch.setattr(b2y, "module_report", interrupt)

    with pytest.raises(KeyboardInterrupt):
        b2y.apply_plan(plan)

    _assert_legacy_back(repo, folder)


def test_a_backup_removal_cut_short_blocks_no_later_run(repo: Path, monkeypatch):
    import shutil

    folder = _legacy(repo)
    monkeypatch.setattr(b2y, "convert_file", _fake_convert())
    monkeypatch.setattr(
        b2y,
        "validate_configs",
        lambda configs, support_yamls: [
            {"ioc_name": n, "status": "ok"} for n in configs
        ],
    )
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if str(path).endswith(b2y.DISCARD_SUFFIX) and Path(path).exists():
            (Path(path) / "values.yaml").unlink()
            raise KeyboardInterrupt
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    with pytest.raises(KeyboardInterrupt):
        b2y.apply_plan(b2y.build_plan("BL11I", repo))
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)

    # the validated IOC stays converted, and no backup is left to block
    assert (folder / "config" / "ioc.yaml").is_file()
    services = repo / "services"
    assert not list(services.glob(f".*{b2y.BACKUP_SUFFIX}"))
    plan = b2y.build_plan("BL11I", repo)
    assert plan.failures == []
    # the next --apply removes what is left
    b2y.apply_plan(plan, validate=False)
    assert not list(services.glob(f".*{b2y.DISCARD_SUFFIX}"))
