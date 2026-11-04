"""What a run does when something goes wrong: nothing lost quietly, nobody's work overwritten,
and a gated write stays gated however the screen gates it."""

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).parent.parent
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(TOOL / "example"))
import edl  # noqa: E402
import gen  # noqa: E402
import make_example as mx  # noqa: E402
import protect  # noqa: E402
import pvi_from_edm  # noqa: E402
import release  # noqa: E402
import settings  # noqa: E402
import sweep  # noqa: E402
import validate  # noqa: E402
from settings import CFG  # noqa: E402

needs_msi = pytest.mark.skipif(not shutil.which("msi"), reason="no msi on PATH")
RELEASE = "prod/support/demoHeater/1-0"
DEMO = "support/demoHeater"


def run(root, *args):
    return subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), *map(str, args), "--config", str(root / "pvi-from-edm.yaml"), "--work-dir", str(root / "work")], capture_output=True, text=True)


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    mx.make(root)
    return root


def in_process(root, dry_run=True) -> dict:
    """The settings of `site` in this process, and the one item a sweep would hand a worker."""
    settings.install(pvi_from_edm.configure(pvi_from_edm.common_options().parse_args(["--config", str(root / "pvi-from-edm.yaml"), "--work-dir", str(root / "work")])))
    CFG.status.mkdir(parents=True, exist_ok=True)
    CFG.output.mkdir(parents=True, exist_ok=True)
    items = sweep.inventory()
    item = items[0]
    item.update(key=item["dir"], dry_run=dry_run, taken=sweep.reserved_stems(items))
    return item


def commit(repo):
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=x", "-c", "user.email=x@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "x"], check=True)


def writes(root) -> list[tuple[str, str]]:
    """(the sub-screens a write sits in, its PV), from the generated device."""
    device = yaml.safe_load((root / "work/out/demoHeater/demoHeater.pvi.device.yaml").read_text())

    def walk(tree, path=()):
        for c in tree:
            if c["type"] == "Group":
                yield from walk(c["children"], (*path, c.get("label") or c["name"]))
            elif "write_pv" in c:
                yield " / ".join(path), c["write_pv"]

    return list(walk(device["children"]))


# A module timeout


def test_a_timeout_while_building_a_device_fails_the_module(site, monkeypatch):
    item = in_process(site)

    def late(*_):
        raise settings.ModuleTimeout("module timed out")

    monkeypatch.setattr(gen, "build_device", late)
    st = sweep.run_item(item)
    assert st["status"] == "failed" and "timed out" in st["reason"]
    assert not st.get("device_errors")


# Uncommitted work


def _hand_work(root):
    folder = root / DEMO
    (folder / "mine.pvi.device.yaml").write_text("label: mine\nchildren: []\n")
    y = folder / "demoHeater.ibek.support.yaml"
    y.write_text(y.read_text() + "# my edit\n")
    return folder, y


def test_a_sweep_refuses_a_folder_with_uncommitted_work(site):
    folder, y = _hand_work(site)
    p = run(site, "sweep", "--jobs", 1)
    assert p.returncode == 1
    assert "uncommitted" in p.stdout and "mine.pvi.device.yaml" in p.stdout
    assert (folder / "mine.pvi.device.yaml").exists() and "# my edit" in y.read_text()


def test_a_narrowed_sweep_refuses_too(site):
    folder, y = _hand_work(site)
    assert run(site, "sweep", "--jobs", 1, "demoHeater").returncode == 1
    assert (folder / "mine.pvi.device.yaml").exists() and "# my edit" in y.read_text()


def test_a_flag_overwrites_uncommitted_work(site):
    folder, y = _hand_work(site)
    p = run(site, "sweep", "--jobs", 1, "--overwrite-uncommitted")
    assert p.returncode == 0, p.stdout
    assert not (folder / "mine.pvi.device.yaml").exists() and "# my edit" not in y.read_text()


def test_a_dry_run_says_a_folder_has_uncommitted_work(site):
    folder, y = _hand_work(site)
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert "uncommitted" in p.stdout and "mine.pvi.device.yaml" in p.stdout
    assert (folder / "mine.pvi.device.yaml").exists() and "# my edit" in y.read_text()


def test_a_sweep_replaces_what_it_installed_itself(site):
    assert run(site, "sweep", "--jobs", 1).returncode == 0
    p = run(site, "sweep", "--jobs", 1)
    assert p.returncode == 0, p.stdout


def test_a_hand_edit_of_what_it_installed_is_uncommitted_work(site):
    assert run(site, "sweep", "--jobs", 1).returncode == 0
    device = site / DEMO / "demoHeater.pvi.device.yaml"
    device.write_text(device.read_text() + "# my edit\n")
    assert run(site, "sweep", "--jobs", 1).returncode == 1
    assert "# my edit" in device.read_text()


def test_other_uncommitted_files_of_a_folder_are_left_out_of_it(site):
    (site / DEMO / "notes.txt").write_text("not the tool's to touch")
    p = run(site, "sweep", "--jobs", 1)
    assert p.returncode == 0, p.stdout
    assert (site / DEMO / "notes.txt").exists()


def test_a_rename_is_read_as_its_new_path(site):
    repo = site / "support"
    subprocess.run(["git", "-C", str(repo), "mv", "demoHeater/demoHeater.install.yml", "demoHeater/renamed.install.yml"], check=True)
    assert sweep.changed_in_repo(repo) == ["demoHeater/renamed.install.yml"]


# Exit code and what gets printed


def test_a_sweep_fails_when_a_module_fails(site):
    shutil.rmtree(site / "prod")
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert p.returncode == 1 and "no_release" in p.stdout


def test_a_sweep_refuses_a_folder_it_does_not_know(site):
    p = run(site, "sweep", "--jobs", 1, "--dry-run", "demoHeatr")
    assert p.returncode != 0 and "demoHeatr" in p.stdout + p.stderr
    assert not (site / "work" / "out" / "demoHeater").exists()


def _done(**kw):
    return {"dir": "mod", "status": "done", "entity_failures": {}, "device_errors": {}, **kw}


def test_a_lost_entity_is_printed_with_its_reason_and_fails_the_run(capsys):
    results = [_done(entity_failures={"one": dict(cls="test_instance", reason="'x' is undefined")}, device_errors={"two": dict(cls="no_record_placed", reason="no record placed")})]
    assert sweep.summarise(results) == 1
    out = capsys.readouterr().out
    assert "mod/one" in out and "'x' is undefined" in out and "mod/two" in out and "no record placed" in out


def test_an_expected_loss_is_printed_and_does_not_fail_the_run(capsys):
    CFG.expected_losses = {("mod", "one"): _loss(reason="needs a list the stand-in does not supply")}
    results = [_done(entity_failures={"one": dict(cls="test_instance", reason="'x' is undefined")})]
    assert sweep.summarise(results) == 0
    assert "needs a list the stand-in does not supply" in capsys.readouterr().out


def test_an_expected_module_failure_needs_its_own_entry(capsys):
    failed = dict(dir="mod", status="failed", cls="no_screen_match", reason="none matches")
    assert sweep.summarise([failed]) == 1
    CFG.expected_losses = {("mod", ""): _loss("no_screen_match", reason="its screens are for another record set")}
    assert sweep.summarise([failed]) == 0
    assert "its screens are for another record set" in capsys.readouterr().out


@pytest.mark.parametrize("cls", ["tool_exception", "uncommitted_changes", "retries_exhausted"])
def test_listing_a_module_as_expected_does_not_excuse_a_broken_run(cls):
    CFG.expected_losses = {("mod", ""): _loss(cls)}
    assert sweep.summarise([dict(dir="mod", status="failed", cls=cls, reason="x")]) == 1


def test_an_expected_loss_entry_that_matches_nothing_is_reported(capsys):
    CFG.expected_losses = {("mod", "gone"): _loss()}
    assert sweep.summarise([_done()]) == 0
    assert "mod/gone" in capsys.readouterr().out


def test_settings_read_expected_losses_and_refuse_one_with_no_reason(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("expected_losses:\n  - {folder: a, entity: b, class: test_instance, matches: x, reason: why}\n  - {folder: c, class: no_release, reason: all of it}\n")
    assert settings.from_file(f).expected_losses == {("a", "b"): {"class": "test_instance", "matches": "x", "reason": "why"}, ("c", ""): {"class": "no_release", "matches": "", "reason": "all of it"}}
    f.write_text("expected_losses:\n  - {folder: a, class: no_release}\n")
    with pytest.raises(ValueError, match="reason"):
        settings.from_file(f)


# An exhausted retry loop


def test_a_failure_in_the_last_round_is_not_installed(site, monkeypatch):
    item = in_process(site, dry_run=False)
    real = sweep.validate_stage
    rounds = []

    def always_one_more(key, ov, outdir, defs):
        rounds.append(1)
        val = real(key, ov, outdir, defs)
        val["entities"]["controller"] = dict(ok=False, cls="pv_missing", reason="made up")
        return val

    monkeypatch.setattr(sweep, "validate_stage", always_one_more)
    st = sweep.run_item(item)
    assert st["status"] == "failed" and st["cls"] == "retries_exhausted"
    assert "controller" in st["entity_failures"]
    assert not (site / DEMO / "demoHeater.pvi.device.yaml").exists()
    assert "pvi:" not in (site / DEMO / "demoHeater.ibek.support.yaml").read_text()


# Versions


@pytest.mark.parametrize(
    ("want", "validated", "same"),
    [("1-0", "1-0", True), ("1.0", "1-0", True), ("1-0ec2", "1-0", True), ("3.3.0", "3-2-1", False), ("epics-containers", "1-24", False), ("1-0", "1-0dls3", False)],
)
def test_an_install_version_against_a_release(want, validated, same):
    assert release.same_version(want, validated) is same


def _bump_install(root, version):
    f = root / DEMO / "demoHeater.install.yml"
    f.write_text(f"module: demoHeater\nversion: {version}\n")
    commit(root / "support")


def test_a_release_other_than_install_yml_is_a_warning(site):
    _bump_install(site, "9-9")
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert p.returncode == 0, p.stdout
    # on its own line, and again in the summary
    assert p.stdout.count("install.yml builds 9-9") == 2 and "validated against 1-0" in p.stdout
    status = json.loads((site / "work" / "sweep-status.json").read_text())
    assert "9-9" in status["demoHeater"]["version_warning"]


def test_a_version_means_nothing_for_a_module_that_generated_nothing(capsys):
    assert sweep.summarise([dict(dir="mod", status="skipped", cls="no_device_screen", version_warning="mod: install.yml builds 9-9")]) == 0
    assert "9-9" not in capsys.readouterr().out


def test_a_known_version_difference_can_be_accepted(site):
    _bump_install(site, "9-9")
    with (site / "pvi-from-edm.yaml").open("a") as f:
        f.write("accepted_versions:\n  - {folder: demoHeater, install: 9-9, validated: 1-0, reason: the records match}\n")
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert p.returncode == 0 and "WARNING" not in p.stdout
    assert "the records match" in p.stdout


def test_an_install_placeholder_names_no_version(site):
    _bump_install(site, "SOMEBUILD")
    with (site / "pvi-from-edm.yaml").open("a") as f:
        f.write("install_placeholders: [SOMEBUILD]\n")
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert "install.yml builds" not in p.stdout and "names no version" in p.stdout


def _checkout(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    (path / "f").write_text("1")
    commit(path)
    subprocess.run(["git", "-C", str(path), "tag", "2-0"], check=True)
    (path / "f").write_text("2")
    commit(path)
    return path


def test_a_checkout_is_held_to_the_version_install_yml_builds(tmp_path):
    co = _checkout(tmp_path / "co")
    assert "2-0" in validate.checkout_version_problem(co, "2-0")
    subprocess.run(["git", "-C", str(co), "checkout", "-q", "2-0"], check=True)
    assert validate.checkout_version_problem(co, "2-0") == ""
    assert "no such version" in validate.checkout_version_problem(co, "7-7")
    assert validate.checkout_version_problem(co, "") == ""
    head = subprocess.run(["git", "-C", str(co), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (co / ".git" / "FETCH_HEAD").write_text(f"{head}\t\ttag '7-7' of https://example.invalid/co\n")
    assert validate.checkout_version_problem(co, "7-7") == ""
    assert validate.checkout_version_problem(co, "7-8") != ""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert "not a git checkout" in validate.checkout_version_problem(plain, "2-0")


def test_a_same_named_test_template_does_not_shadow_the_real_one(tmp_path):
    CFG.msi = Path("/bin/true")
    co = tmp_path / "co"
    for rel, text in (("aTest/thing.template", "test\n"), ("thingApp/Db/thing.template", "real\n"), ("zExtra/other.template", "other\n")):
        (co / rel).parent.mkdir(parents=True, exist_ok=True)
        (co / rel).write_text(text)
    build, _, shadowed = validate.layout_release(co, tmp_path / "build", [], [])
    assert (build / "db" / "thing.template").read_text() == "real\n"
    assert (build / "db" / "other.template").read_text() == "other\n"
    assert shadowed == []


def test_two_real_templates_of_one_name_are_reported(tmp_path):
    CFG.msi = Path("/bin/true")
    co = tmp_path / "co"
    for rel, text in (("aApp/Db/thing.template", "a\n"), ("bApp/Db/thing.template", "b\n")):
        (co / rel).parent.mkdir(parents=True, exist_ok=True)
        (co / rel).write_text(text)
    _, _, shadowed = validate.layout_release(co, tmp_path / "build", [], [])
    assert len(shadowed) == 1 and "thing.template" in shadowed[0] and "aApp/Db" in shadowed[0]


def _hand_written_site(root, *extra):
    with (root / "pvi-from-edm.yaml").open("a") as f:
        f.write("hand_written: [{repo: demo, folder: demoHeater}]\n" + "".join(extra))
    assert run(root, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    # as a person would have it: the generated device and section, uncommitted
    (root / "support/demoHeater/demoHeater.pvi.device.yaml").write_text(mx_device(root))
    (root / "support/demoHeater/demoHeater.ibek.support.yaml").write_text((root / "support/demoHeater/demoHeater.ibek.support.yaml").read_text().replace(
        "    databases:\n", "    pvi:\n      yaml_path: demoHeater.pvi.device.yaml\n      ui_macros:\n        P:\n      pv_prefix: $(P)\n    databases:\n"))


def mx_device(root):
    return "label: demo\nchildren:\n- type: SignalR\n  name: Temp\n  read_pv: $(P):TEMP\n  read_widget:\n    type: TextRead\n"


def _upstream(root, tmp_path, *rows):
    co = tmp_path / "upstream" / "demoHeater"
    (co / "demoHeaterApp" / "Db").mkdir(parents=True)
    (co / "demoHeaterApp" / "Db" / "demoHeater.template").write_text((root / RELEASE / "db" / "demoHeater.template").read_text())
    for name, text in rows:
        (co / "demoHeaterApp" / "Db" / name).write_text(text)
    subprocess.run(["git", "-C", str(co), "init", "-q"], check=True)
    commit(co)
    return co


@needs_msi
def test_validate_warns_of_a_stale_checkout_and_of_what_msi_refused(site, tmp_path):
    _hand_written_site(site)
    co = _upstream(site, tmp_path, ("bad.substitutions", 'file "gone.template" {\n{ P=x }\n}\n'))
    p = run(site, "validate", "--upstream-root", co.parent)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "WARNING demoHeater: install.yml builds 1-0" in p.stdout
    assert "WARNING demoHeater: msi refused bad.substitutions" in p.stdout
    val = json.loads((site / "work/out/demoHeater/validate.json").read_text())
    assert val["msi_refused"] and val["version_warning"]


@needs_msi
def test_a_known_refusal_and_checkout_can_be_accepted(site, tmp_path):
    co = _upstream(site, tmp_path, ("bad.substitutions", 'file "gone.template" {\n{ P=x }\n}\n'))
    head = subprocess.run(["git", "-C", str(co), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    _hand_written_site(
        site,
        f"accepted_versions:\n  - {{folder: demoHeater, install: 1-0, validated: {head}, reason: checked by hand}}\n",
        "accepted_msi_refusals:\n  - {folder: demoHeater, file: bad.substitutions, reason: an example nobody loads}\n",
    )
    p = run(site, "validate", "--upstream-root", co.parent)
    assert "WARNING" not in p.stdout, p.stdout


# Gates on links


def link_to(file, gate="$(P):MODE", label="Expert", y=170):
    return mx.obj("relatedDisplayClass", 120, y, 100, 20, **({"visPv": gate, "visMin": "1", "visMax": "2"} if gate else {})) .replace(
        "endObjectProperties", f'displayFileName {{\n  0 "{file}"\n}}\nmenuLabel {{\n  0 "{label}"\n}}\nsymbols {{\n  0 "P=$(P)"\n}}\nendObjectProperties'
    )


def small_screen(*objs):
    return "4 0 1\nbeginScreenProperties\nmajor 4\nw 300\nh 300\nendScreenProperties\n" + "\n".join(objs)


def _with_target(root, names, objs, gate="$(P):MODE"):
    rel = root / RELEASE
    with (rel / "db/demoHeater.template").open("a") as f:
        f.write("".join(f'record(ao, "$(P):{n}") {{\n}}\n' for n in names))
    with (rel / "data/demoHeater.edl").open("a") as f:
        f.write(link_to("eng.edl", gate))
    (rel / "data/eng.edl").write_text(small_screen(*objs))


def _entry(rows, y):
    return mx.obj("TextentryClass", 120, y, 100, 20, controlPv=f"$(P):{rows}")


PLAIN = [f"R{i}" for i in range(6)]


def test_writes_behind_a_gated_link_move_to_protected(site):
    _with_target(site, PLAIN, [_entry(n, 10 + 20 * i) for i, n in enumerate(PLAIN)])
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    where = dict((pv, path) for path, pv in writes(site))
    assert all("Protected Controls" in where[f"$(P):{n}"] for n in PLAIN), where
    gated = json.loads((site / "work/gated-writes.json").read_text())
    assert {"$(P):R0"} <= {g["pv"] for g in gated if g.get("via_link")}
    assert all(g["gate_pv"] for g in gated if g.get("via_link"))


def test_an_ungated_link_leaves_its_writes_where_they_are(site):
    _with_target(site, PLAIN, [_entry(n, 10 + 20 * i) for i, n in enumerate(PLAIN)], gate=None)
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    where = dict((pv, path) for path, pv in writes(site))
    assert not any("Protected" in where[f"$(P):{n}"] for n in PLAIN), where


def test_a_small_dialog_behind_a_gated_link_does_not_land_on_the_first_screen(site):
    _with_target(site, ["FIRE"], [_entry("FIRE", 10)])
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    assert "Protected Controls" in dict((pv, path) for path, pv in writes(site))["$(P):FIRE"]


def test_a_confirmation_behind_a_gated_link_moves_and_keeps_its_warning(site):
    warn = mx.text(5, "Are you sure you want to fire this?")
    _with_target(site, ["FIRE"], [warn, _entry("FIRE", 40)])
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    assert "Protected Controls" in dict((pv, path) for path, pv in writes(site))["$(P):FIRE"]
    device = (site / "work/out/demoHeater/demoHeater.pvi.device.yaml").read_text()
    assert "Are you sure you want to fire this? (FIRE)" in device


def test_a_mode_only_write_behind_a_gated_link_stays(site):
    _with_target(site, PLAIN, [_entry(n, 10 + 20 * i) for i, n in enumerate(PLAIN)])
    (site / "classification.yaml").write_text(yaml.safe_dump([
        dict(module="demoHeater", entity="controller", pv="$(P):R0", **{"class": "mode-only"}, evidence="read", judged="person"),
    ]))
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    where = dict((pv, path) for path, pv in writes(site))
    assert "Protected Controls" not in where["$(P):R0"] and "Protected Controls" in where["$(P):R1"]


def _extra_screen(root, *objs):
    """A screen beside the root the entity's override adds, as a search for screens adds one."""
    rel = root / RELEASE
    with (rel / "db/demoHeater.template").open("a") as f:
        f.write('record(bo, "$(P):LOCK") {\n}\n')
    (rel / "data/top.edl").write_text(small_screen(_entry("LOCK", 10), *objs))
    (root / "overrides/demoHeater.sweep.yaml").write_text(yaml.safe_dump({"devices": {"demoHeater": {"extra_screens": [{"file": "top.edl", "label": "Top"}]}}}))


@needs_msi
def test_a_root_only_a_gated_link_opens_is_behind_that_gate(site):
    _extra_screen(site, link_to("demoHeater.edl", gate="$(P):LOCK", y=60))
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    where = dict((pv, path) for path, pv in writes(site))
    assert "Protected Controls" in where["$(P):SP"]
    assert "Protected Controls" not in where["$(P):LOCK"]
    assert run(site, "audit").returncode == 0


@needs_msi
def test_a_gated_link_back_from_a_screen_the_root_opens_gates_nothing(site):
    _with_target(site, PLAIN, [_entry(n, 10 + 20 * i) for i, n in enumerate(PLAIN)] + [link_to("demoHeater.edl", y=150)], gate=None)
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    assert "Protected Controls" not in dict((pv, path) for path, pv in writes(site))["$(P):SP"]
    assert run(site, "audit").returncode == 0


@needs_msi
def test_the_audit_covers_writes_behind_a_gated_link(site):
    _with_target(site, PLAIN, [_entry(n, 10 + 20 * i) for i, n in enumerate(PLAIN)])
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    p = run(site, "audit")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "behind a gated link: 6 writes" in p.stdout
    # the audit reads the screens and the .bob files, not the report
    bobs = list((site / "work/sandbox/demoHeater/opi").glob("*Protected*.pvi.bob"))
    assert bobs
    for b in bobs:
        b.unlink()
    p = run(site, "audit")
    assert p.returncode == 1 and "$(P):R0" in p.stdout


# A class that says to move a write


def test_targets_take_a_listed_dangerous_write_that_is_not_gated():
    children = [dict(type="SignalRW", name="Sp", write_pv="$(P):SP", read_pv="$(P):SP", write_widget=dict(type="TextWrite"))]
    classes = {("m", "e", "$(P):SP"): {"class": "dangerous"}}
    assert protect.targets_of(children, [], classes, "m", "e") == ({"$(P):SP": "dangerous"}, [])


@needs_msi
def test_a_dangerous_entry_on_an_ungated_write_moves_it(site):
    (site / "classification.yaml").write_text(yaml.safe_dump([
        dict(module="demoHeater", entity="controller", pv="$(P):SP", **{"class": "dangerous"}, evidence="a person knows", judged="person"),
    ]))
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert p.returncode == 0 and "match nothing" not in p.stdout
    assert "Protected Controls" in dict((pv, path) for path, pv in writes(site))["$(P):SP"]
    assert run(site, "audit").returncode == 0


# Parsing


def test_a_sparse_edl_array_keeps_its_indices(tmp_path):
    f = tmp_path / "s.edl"
    f.write_text(
        "beginScreenProperties\nw 10\nh 10\nendScreenProperties\nobject relatedDisplayClass\nbeginObjectProperties\nx 1\ny 1\nw 5\nh 5\n"
        'displayFileName {\n  0 "a"\n  1 "b"\n}\nmenuLabel {\n  1 "Bee"\n}\nsymbols {\n  1 "M=2"\n}\nendObjectProperties\n'
    )
    got = [(ln["file"], ln["label"], ln["symbols"]) for ln in edl.links(edl.parse_edl(f).objects[0])]
    assert got == [("a", "", ""), ("b", "Bee", "M=2")]


def test_a_hole_in_the_file_names_of_a_link_is_no_link(tmp_path):
    f = tmp_path / "s.edl"
    f.write_text(
        "beginScreenProperties\nw 10\nh 10\nendScreenProperties\nobject relatedDisplayClass\nbeginObjectProperties\nx 1\ny 1\nw 5\nh 5\n"
        'displayFileName {\n  1 "b"\n}\nmenuLabel {\n  1 "Bee"\n}\nendObjectProperties\n'
    )
    assert [(ln["file"], ln["label"]) for ln in edl.links(edl.parse_edl(f).objects[0])] == [("b", "Bee")]


# Messages rather than tracebacks


@pytest.mark.parametrize("command", [["check"], ["validate"], ["audit"], ["review"], ["evidence"], ["classify"], ["generate", "nomodule"]])
def test_a_missing_input_gets_a_message(site, command):
    p = run(site, *command)
    assert p.returncode != 0
    assert "Traceback" not in p.stderr and p.stderr.strip(), p.stderr


def test_validating_no_hand_written_folder_says_so(site):
    p = run(site, "validate", "--upstream-root", "/nonexistent")
    assert p.returncode != 0 and "no hand-written folder" in p.stderr


def test_a_missing_settings_file_gets_a_message(tmp_path):
    p = subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), "check", "--config", str(tmp_path / "none.yaml")], capture_output=True, text=True)
    assert p.returncode != 0 and "Traceback" not in p.stderr and "none.yaml" in p.stderr


def test_a_bad_settings_file_gets_a_message(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("repoz: {}\n")
    p = subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), "check", "--config", str(f)], capture_output=True, text=True)
    assert p.returncode != 0 and "Traceback" not in p.stderr and "repoz" in p.stderr


def test_a_missing_screen_gets_a_message(tmp_path):
    p = subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), "dump-edl", str(tmp_path / "none.edl")], capture_output=True, text=True)
    assert p.returncode != 0 and "Traceback" not in p.stderr and "none.edl" in p.stderr


def test_a_sweep_says_what_it_needs_to_know(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    p = subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), "sweep", "--repo", str(repo), "--work-dir", str(tmp_path / "w")], capture_output=True, text=True)
    assert p.returncode != 0 and "Traceback" not in p.stderr and "--prod-root" in p.stderr


def test_the_tool_knows_no_site_by_default():
    s = settings.Settings()
    assert s.prod == [] and s.work == [] and s.older == [] and s.last_resort_modules == []
    assert s.msi is None and s.base_dbd is None and not s.support_dbd_glob


# What an audit leaves out


@needs_msi
def test_the_audit_says_what_it_did_not_check(site):
    rel = site / RELEASE
    sup = site / DEMO / "demoHeater.ibek.support.yaml"
    sup.write_text(sup.read_text() + "  - name: broken\n    description: d\n    parameters:\n      P:\n        type: str\n        description: d\n    databases:\n      - file: $(DEMOHEATER)/db/none.template\n        args:\n          P:\n")
    commit(site / "support")
    assert rel.exists()
    run(site, "sweep", "--jobs", 1, "--dry-run")
    p = run(site, "audit")
    assert "not checked:" in p.stdout
    assert "entities not in a device" in p.stdout or "lost" in p.stdout


def test_no_msi_is_said_by_a_sweep_and_an_audit(site):
    def plain(*args):
        command = [sys.executable, str(TOOL / "pvi_from_edm.py"), *map(str, args), "--msi", "/nonexistent", "--config", str(site / "pvi-from-edm.yaml"), "--work-dir", str(site / "work")]
        return subprocess.run(command, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})

    assert "no msi found" in plain("sweep", "--jobs", 1, "--dry-run").stdout
    p = plain("audit")
    assert p.returncode == 1 and "no msi was run" in p.stdout


# A timeout an OSError handler would swallow


def test_a_timeout_during_a_quiet_rmtree_still_fails_the_module(site, tmp_path, monkeypatch):
    """shutil.rmtree(ignore_errors=True) drops any OSError, and the alarm fires only once."""
    item = in_process(site)
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    (doomed / "f").write_text("x")
    real_process = gen.process

    def alarm_in_rmtree(*a, **kw):
        real_unlink = os.unlink

        def unlink(*a2, **kw2):
            monkeypatch.setattr(os, "unlink", real_unlink)
            signal.raise_signal(signal.SIGALRM)
            return real_unlink(*a2, **kw2)

        monkeypatch.setattr(os, "unlink", unlink)
        shutil.rmtree(doomed, ignore_errors=True)
        return real_process(*a, **kw)

    monkeypatch.setattr(sweep, "process", alarm_in_rmtree)
    st = sweep.run_item(item)
    assert st["status"] == "failed" and st["cls"] == "tool_exception" and "timed out" in st["reason"]


# What expected_losses excuses


def _loss(cls="test_instance", matches="", reason="known"):
    return {"class": cls, "matches": matches, "reason": reason}


def test_an_expected_loss_excuses_only_its_own_class(capsys):
    CFG.expected_losses = {("mod", "one"): _loss("test_instance")}
    assert sweep.summarise([_done(entity_failures={"one": dict(cls="pv_missing", reason="3 PVs missing")})]) == 1
    assert "lost, failing this run" in capsys.readouterr().out


def test_an_expected_loss_excuses_only_the_text_it_names():
    CFG.expected_losses = {("mod", "one"): _loss("test_instance", matches="'x' is undefined")}
    assert sweep.summarise([_done(entity_failures={"one": dict(cls="test_instance", reason="Error: 'x' is undefined")})]) == 0
    assert sweep.summarise([_done(entity_failures={"one": dict(cls="test_instance", reason="Error: 'y' is undefined")})]) == 1


@pytest.mark.parametrize("cls", ["validator_error", "public_hygiene", "yaml_changed", "tool_exception"])
def test_a_crash_or_a_refusal_is_never_an_expected_loss(cls):
    CFG.expected_losses = {("mod", "one"): _loss(cls), ("mod", ""): _loss(cls)}
    assert sweep.summarise([_done(entity_failures={"one": dict(cls=cls, reason="x")})]) == 1
    assert sweep.summarise([dict(dir="mod", status="failed", cls=cls, reason="x")]) == 1


def test_a_type_error_is_never_an_expected_loss_whatever_its_class():
    CFG.expected_losses = {("mod", "one"): _loss("test_instance")}
    assert sweep.summarise([_done(entity_failures={"one": dict(cls="test_instance", reason="TypeError: bad operand")})]) == 1


def test_a_device_that_crashed_is_not_excused_by_an_entry_for_its_usual_loss():
    CFG.expected_losses = {("mod", "dev"): _loss("no_record_placed")}
    assert sweep.summarise([_done(device_errors={"dev": dict(cls="no_record_placed", reason="no record of a is placed by b")})]) == 0
    assert sweep.summarise([_done(device_errors={"dev": dict(cls="exception", reason="KeyError: 'x'")})]) == 1


def test_a_module_entry_does_not_excuse_a_crash_among_its_entities():
    """A module that generates nothing takes one class, and that must not hide the others."""
    CFG.expected_losses = {("mod", ""): _loss("test_instance")}
    failed = dict(dir="mod", status="failed", cls="test_instance", reason="x", entity_failures={"a": dict(cls="test_instance", reason="x"), "b": dict(cls="validator_error", reason="KeyError")})
    assert sweep.summarise([failed]) == 1


def test_a_module_that_crashed_on_every_device_says_so(site, monkeypatch):
    item = in_process(site)

    def crash(*a):
        raise KeyError("boom")

    monkeypatch.setattr(gen, "build_device", crash)
    st = sweep.run_item(item)
    assert st["status"] == "failed" and st["cls"] == "tool_exception" and "boom" in st["reason"]


def test_settings_refuse_an_expected_loss_with_no_class_or_one_that_cannot_be_excused(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("expected_losses:\n  - {folder: a, reason: why}\n")
    with pytest.raises(ValueError, match="class"):
        settings.from_file(f)
    f.write_text("expected_losses:\n  - {folder: a, class: validator_error, reason: why}\n")
    with pytest.raises(ValueError, match="validator_error"):
        settings.from_file(f)


def test_an_expected_loss_for_a_folder_no_repo_has_is_reported(site):
    text = (site / "pvi-from-edm.yaml").read_text()
    (site / "pvi-from-edm.yaml").write_text(text + "expected_losses:\n  - {folder: demoHeatr, class: no_release, reason: a slip}\n")
    p = run(site, "sweep", "--jobs", 1, "--dry-run", "demoHeater")
    assert "expected_losses" in p.stdout and "demoHeatr" in p.stdout


# generate --write


def _pin(root):
    (root / "overrides/demoHeater.yaml").write_text(yaml.safe_dump({"repo": "demo", "release": str(root / RELEASE)}))


def test_generate_write_refuses_uncommitted_work(site):
    _pin(site)
    folder, y = _hand_work(site)
    (folder / "demoHeater.pvi.device.yaml").write_text("label: mine\nchildren: []\n")
    p = run(site, "generate", "demoHeater", "--write")
    assert p.returncode == 1 and "uncommitted" in p.stdout + p.stderr
    assert "# my edit" in y.read_text() and "mine" in (folder / "demoHeater.pvi.device.yaml").read_text()


def test_generate_write_with_the_flag_overwrites(site):
    _pin(site)
    _folder, y = _hand_work(site)
    p = run(site, "generate", "demoHeater", "--write", "--overwrite-uncommitted")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "# my edit" not in y.read_text()


def test_generate_without_write_ignores_uncommitted_work(site):
    _pin(site)
    _folder, y = _hand_work(site)
    assert run(site, "generate", "demoHeater").returncode == 0
    assert "# my edit" in y.read_text()


def test_generate_write_records_what_it_installed(site):
    _pin(site)
    assert run(site, "generate", "demoHeater", "--write").returncode == 0
    mine = json.loads((site / "work/installed.json").read_text())
    assert {"demo/demoHeater/demoHeater.ibek.support.yaml", "demo/demoHeater/demoHeater.pvi.device.yaml"} <= set(mine)
    # so writing again is no conflict with itself, and a sweep can tell it from a person's work
    assert run(site, "generate", "demoHeater", "--write").returncode == 0


# Device name collisions


def test_a_device_name_collision_fails_a_full_sweep(site):
    assert run(site, "sweep", "--jobs", 1, "--dry-run").returncode == 0
    (site / "support/other").mkdir()
    (site / "support/other/demoHeater.pvi.device.yaml").write_text("label: other\nchildren: []\n")
    (site / DEMO / "demoHeater.pvi.device.yaml").write_text("label: x\nchildren: []\n")
    p = run(site, "sweep", "--jobs", 1, "--dry-run")
    assert p.returncode == 1 and "device name collisions" in p.stdout and "support/other" in p.stdout.replace("demo/", "support/")
