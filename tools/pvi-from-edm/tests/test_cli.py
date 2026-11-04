"""The command line, the settings file, and a whole run on the made-up example."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOL = Path(__file__).parent.parent
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(TOOL / "example"))
import classify  # noqa: E402
import make_example  # noqa: E402
import protect  # noqa: E402
import pvi_from_edm  # noqa: E402
import release  # noqa: E402
import settings  # noqa: E402
import sweep  # noqa: E402
from settings import CFG  # noqa: E402


needs_msi = pytest.mark.skipif(not shutil.which("msi"), reason="no msi on PATH")


def run(*args, check=True):
    p = subprocess.run([sys.executable, str(TOOL / "pvi_from_edm.py"), *map(str, args)], capture_output=True, text=True)
    if check:
        assert p.returncode == 0, p.stdout + p.stderr
    return p


def test_a_settings_file_holds_paths_relative_to_itself(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(
        yaml.safe_dump(
            dict(
                repos={"a": "repo-a"},
                public_repos=["a"],
                prod_roots=["rel"],
                classification="c.yaml",
                hand_written=[dict(repo="a", folder="byhand")],
                forks=[dict(repo="a", folder="x", twin_repo="b", twin_folder="x_fork")],
                reserved_stems=[dict(stem="s", repo="a", folder="x")],
                release_aliases={"x": "devX"},
            )
        )
    )
    s = settings.from_file(f)
    assert s.repos == {"a": tmp_path / "repo-a"}
    assert s.prod == [tmp_path / "rel"]
    assert s.classification == tmp_path / "c.yaml"
    assert s.hand_written == {("a", "byhand")}
    assert s.forks == {("a", "x"): ("b", "x_fork")}
    assert s.fork_twins() == {("b", "x_fork"): ("a", "x")}
    assert s.reserved_stems == [("s", "a", "x")]


def test_an_unknown_setting_stops_the_run(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("repoz: {}\n")
    with pytest.raises(ValueError, match="repoz"):
        settings.from_file(f)


def test_a_repo_key_defaults_to_its_folder_name(tmp_path):
    p = pvi_from_edm.common_options().parse_args(["--repo", "some/support", "--repo", f"k={tmp_path}"])
    s = pvi_from_edm.configure(p)
    assert s.repos["support"].name == "support"
    assert s.repos["k"] == tmp_path.resolve()
    assert s.output.parts[-2:] == ("pvi-from-edm-work", "out")


def test_output_folders_take_their_own_arguments(tmp_path):
    a = pvi_from_edm.common_options().parse_args(["--work-dir", str(tmp_path), "--review-dir", str(tmp_path / "r")])
    s = pvi_from_edm.configure(a)
    assert (s.output, s.review, s.status) == (tmp_path / "out", tmp_path / "r", tmp_path)


def test_settings_naming_an_unknown_repo_are_refused(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("hand_written: [{repo: gone, folder: x}]\n")
    a = pvi_from_edm.common_options().parse_args(["--config", str(f), "--repo", f"k={tmp_path}"])
    with pytest.raises(SystemExit, match="gone"):
        pvi_from_edm.configure(a)


def test_a_release_alias_is_a_name_to_look_for():
    assert release.names_for("thing", "thing", {}) == ["thing"]
    CFG.release_aliases = {"thing": "devThing"}
    assert release.names_for("thing", "thing", {}) == ["thing", "devThing"]


def test_a_configured_module_answers_a_bare_include(tmp_path):
    (tmp_path / "base" / "1-0" / "db").mkdir(parents=True)
    CFG.prod = [tmp_path]
    CFG.last_resort_modules = ["base"]
    assert release.last_resort() == [tmp_path / "base" / "1-0" / "db"]


def test_with_no_classification_file_there_are_no_entries():
    assert protect.load_classes() == {}


def test_a_named_classification_file_must_exist(tmp_path):
    CFG.classification = tmp_path / "gone.yaml"
    with pytest.raises(FileNotFoundError):
        protect.load_classes()


def _evidence(**kw):
    return {"module": "m", "entity": "e", "pv": "$(P):THING", "gates": [["$(P):G", "x"]], "dialog_text": [], "behind_dialog": False, "record": {"desc": ""}, "gate_records": {"$(P):G": {"type": "mbbo", "states": ["A", "B"]}}, "screen_warnings": [], "labels": [], **kw}


def test_a_rule_read_from_the_file_comes_before_the_mode_only_rules(tmp_path):
    assert classify.rule_for(_evidence())[0] == "mode-only"
    (tmp_path / "r.yaml").write_text(yaml.safe_dump(dict(read=[{"module": "m|n", "pv": "THING$", "class": "dangerous", "evidence": "it says so", "names_only": True}])))
    CFG.classify_rules = tmp_path / "r.yaml"
    classify.site_rules.cache_clear()
    assert classify.rule_for(_evidence()) == ("dangerous", "read", "it says so", True)
    assert classify.rule_for(_evidence(module="other"))[0] == "mode-only"


def test_a_last_rule_only_answers_what_nothing_else_did(tmp_path):
    (tmp_path / "r.yaml").write_text(yaml.safe_dump(dict(read_last=[{"pv": "THING$", "class": "mode-only", "evidence": "last", "names_only": False}])))
    CFG.classify_rules = tmp_path / "r.yaml"
    classify.site_rules.cache_clear()
    assert classify.rule_for(_evidence())[1] == "rule:selector-gate"
    assert classify.rule_for(_evidence(gate_records={"$(P):G": {"type": "ai"}}))[:3] == ("mode-only", "read", "last")


def test_an_engineering_gate_comes_from_the_rules_file(tmp_path):
    r = _evidence(gates=[["$(P):EngVis", "x"]], gate_records={})
    assert classify.rule_for(r)[0] == "unsure"
    (tmp_path / "r.yaml").write_text(yaml.safe_dump(dict(engineering_gates=[dict(pattern="EngVis", evidence="engineering only")])))
    CFG.classify_rules = tmp_path / "r.yaml"
    classify.site_rules.cache_clear()
    assert classify.rule_for(r) == ("dangerous", "rule:engineering-gate", "engineering only", True)


def test_a_folder_with_its_own_override_is_pinned(tmp_path):
    assert not sweep.pinned("x")
    CFG.overrides = tmp_path
    (tmp_path / "x.yaml").write_text("{}")
    (tmp_path / "y.sweep.yaml").write_text("{}")
    assert sweep.pinned("x")
    assert not sweep.pinned("y")


def test_reserved_names_come_from_settings_and_the_collision_list(tmp_path, monkeypatch):
    CFG.repos = {}
    CFG.reserved_stems = [("stem", "one", "folder")]
    CFG.collisions = tmp_path / "c.json"
    CFG.collisions.write_text('["clash"]')
    taken = sweep.reserved_stems([])
    assert taken["stem"] == {"one/folder"}
    assert taken["clash"] == {"sweep/*"}


@pytest.fixture
def example(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    make_example.make(root)
    return root


def _common(root):
    return ["--config", root / "pvi-from-edm.yaml", "--work-dir", root / "work"]


@needs_msi
def test_a_whole_run_on_the_example(example):
    common = _common(example)
    repo = example / "support" / "demoHeater"
    before = sorted(p.name for p in repo.iterdir())

    # a dry run leaves the repo alone, and check says what an install would change
    out = run("sweep", "--dry-run", "--jobs", 1, *common).stdout
    assert "demoHeater done validated" in out
    assert sorted(p.name for p in repo.iterdir()) == before
    p = run("check", *common, check=False)
    assert p.returncode == 1 and "missing from the repo: demo/demoHeater/demoHeater.pvi.device.yaml" in p.stdout

    # with an empty classification, every gated write is on the protected screen
    device = (example / "work" / "out" / "demoHeater" / "demoHeater.pvi.device.yaml").read_text()
    assert yaml.safe_load(device)["children"][-1]["label"] == "Protected Controls"
    assert device.count("write_pv: $(P):ENABLE") == 1 and device.count("write_pv: $(P):RATE") == 1

    # classify judges them from the evidence: a rule from the rules file, a name rule
    run("evidence", *common)
    run("classify", *common)
    classes = {e["pv"]: e for e in yaml.safe_load((example / "classification.yaml").read_text())}
    assert classes["$(P):RATE"]["class"] == "mode-only" and classes["$(P):RATE"]["judged"] == "read"
    assert classes["$(P):ENABLE"]["class"] == "dangerous" and classes["$(P):ENABLE"]["judged"] == "rule:name-heater"
    run("sweep", "--dry-run", "--jobs", 1, *common)
    device = yaml.safe_load((example / "work" / "out" / "demoHeater" / "demoHeater.pvi.device.yaml").read_text())
    protected = next(c for c in device["children"] if c.get("label") == "Protected Controls")
    assert "$(P):RATE" not in str(protected) and "$(P):ENABLE" in str(protected)

    # the audit reads the screens and the .bob files, and the review pages get written
    assert "writable elsewhere 0" in run("audit", *common).stdout
    run("review", *common)
    assert (example / "work" / "review" / "demoHeater.html").exists()
    assert (example / "work" / "review" / "gated-review.html").exists()
    assert "1 of 1 entities pass" in run("validate", *common).stdout

    # an install, then check finds nothing
    run("sweep", "--jobs", 1, *common)
    assert (repo / "demoHeater.pvi.device.yaml").exists()
    assert "0 different; 0 changed" in run("check", *common).stdout
    status = json.loads((example / "work" / "sweep-status.json").read_text())
    assert status["demoHeater"]["status"] == "done"

    # a stray file in the repo, and a changed one, are both reported
    (repo / "stray.pvi.device.yaml").write_text("x")
    (repo / "demoHeater.pvi.device.yaml").write_text("changed")
    p = run("check", *common, check=False)
    assert p.returncode == 1 and "differs: demo/demoHeater/demoHeater.pvi.device.yaml" in p.stdout and "stray.pvi.device.yaml" in p.stdout


def test_classify_can_leave_the_classification_file_as_it_is(example):
    common = _common(example)
    run("sweep", "--dry-run", "--jobs", 1, *common)
    run("evidence", *common)
    run("classify", "--out", example / "other.yaml", *common)
    assert (example / "classification.yaml").read_text() == "[]\n"
    assert "ENABLE" in (example / "other.yaml").read_text()


def test_a_hand_written_folder_is_not_compared_and_not_touched(example):
    (example / "pvi-from-edm.yaml").write_text((example / "pvi-from-edm.yaml").read_text() + "hand_written: [{repo: demo, folder: demoHeater}]\n")
    common = _common(example)
    assert "demoHeater done" not in run("sweep", "--jobs", 1, *common).stdout
    assert not (example / "support" / "demoHeater" / "demoHeater.pvi.device.yaml").exists()
    assert json.loads((example / "work" / "sweep-status.json").read_text())["demoHeater"]["status"] == "hand_written"


def test_a_public_repo_fails_on_the_hygiene_pattern(example):
    text = (example / "pvi-from-edm.yaml").read_text()
    (example / "pvi-from-edm.yaml").write_text(text + "public_repos: [demo]\nhygiene_pattern: 'Temperature'\n")
    p = run("sweep", "--jobs", 1, *_common(example), check=False)
    assert p.returncode == 1 and "failed public_hygiene" in p.stdout
    assert not (example / "support" / "demoHeater" / "demoHeater.pvi.device.yaml").exists()


def test_a_fork_is_generated_once_and_installed_in_both(example):
    twin = example / "other" / "demoHeater_fork"
    twin.mkdir(parents=True)
    source = example / "support" / "demoHeater"
    (twin / "demoHeater.ibek.support.yaml").write_text((source / "demoHeater.ibek.support.yaml").read_text())
    subprocess.run(["git", "-C", str(twin.parent), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(twin.parent), "add", "."], check=True)
    subprocess.run(["git", "-C", str(twin.parent), "-c", "user.name=x", "-c", "user.email=x@example.invalid", "commit", "--quiet", "-m", "x"], check=True)
    text = (example / "pvi-from-edm.yaml").read_text().replace("  demo: support\n", "  demo: support\n  other: other\n")
    (example / "pvi-from-edm.yaml").write_text(text + "forks: [{repo: demo, folder: demoHeater, twin_repo: other, twin_folder: demoHeater_fork}]\n")
    common = _common(example)
    run("sweep", "--jobs", 1, *common)
    assert (twin / "demoHeater.pvi.device.yaml").read_bytes() == (source / "demoHeater.pvi.device.yaml").read_bytes()
    assert json.loads((example / "work" / "sweep-status.json").read_text())["demoHeater_fork"]["status"] == "fork_twin"
    assert "compared 4 files: 0 different" in run("check", *common).stdout


def test_a_repo_must_be_the_top_of_a_git_checkout(example):
    inside = example / "support" / "demoHeater"
    p = run("sweep", "--dry-run", "--repo", f"demo={inside}", "--work-dir", example / "work", check=False)
    assert p.returncode != 0 and "not the top of a git checkout" in p.stderr


def test_dump_edl_prints_rows(example):
    edl_file = example / "prod" / "support" / "demoHeater" / "1-0" / "data" / "demoHeater.edl"
    assert "read:$(P):TEMP" in run("dump-edl", edl_file).stdout


# Validating hand-written folders against a checkout


def _hand_written(example):
    """demoHeater as a hand-written folder, its device including one from another folder."""
    support = example / "support"
    (example / "pvi-from-edm.yaml").write_text((example / "pvi-from-edm.yaml").read_text() + "hand_written: [{repo: demo, folder: demoHeater}]\n")
    common = _common(example)
    (support / "shared").mkdir()
    (support / "shared" / "Shared.pvi.device.yaml").write_text(
        "label: Shared\nchildren:\n- type: SignalR\n  name: Spare\n  read_pv: $(P):SPARE\n  read_widget:\n    type: TextRead\n"
    )
    run("sweep", "--jobs", 1, "--dry-run", *common)
    return common


def _install_by_hand(example):
    """What a person would write: the generated device, the section, and an Include."""
    run("sweep", "--dry-run", "--jobs", 1, *_common(example))
    out = example / "work" / "out" / "demoHeater"
    folder = example / "support" / "demoHeater"
    (folder / "demoHeater.pvi.device.yaml").write_text((out / "demoHeater.pvi.device.yaml").read_text().replace("children:\n", "children:\n- type: Include\n  file_name: Shared\n", 1))
    (folder / "demoHeater.ibek.support.yaml").write_text((out / "demoHeater.ibek.support.yaml").read_text())


def _checkout(example, tmp_path):
    """demoHeater's release as a checkout, with one more record, and a dependency holding SPARE."""
    root = tmp_path / "upstream"
    (root / "demoHeater" / "demoHeaterApp" / "Db").mkdir(parents=True)
    for f in (example / "prod" / "support" / "demoHeater" / "1-0" / "db").iterdir():
        (root / "demoHeater" / "demoHeaterApp" / "Db" / f.name).write_text(f.read_text() + 'record(ai, "$(P):SPARE") {}\nrecord(calc, "$(P):HELP") {}\nrecord(bo, "$(P):NOTSHOWN") {}\n')
    return root


@needs_msi
def test_validate_takes_a_hand_written_folder_from_its_checkout(example, tmp_path):
    _install_by_hand(example)
    common = _hand_written(example)
    p = run("validate", "--upstream-root", _checkout(example, tmp_path), *common)
    assert "demoHeater (upstream checkout at" in p.stdout and "1 of 1 entities pass" in p.stdout, p.stdout
    val = json.loads((example / "work" / "out" / "demoHeater" / "validate.json").read_text())["entities"]["controller"]
    assert val["ok"] and val["generate_matches_generate2"] and "$(P):HELP" in val["records_unused"]


@needs_msi
def test_a_public_hand_written_folder_needs_its_checkout_and_lists_what_it_leaves_out(example, tmp_path):
    _install_by_hand(example)
    text = (example / "pvi-from-edm.yaml").read_text()
    (example / "pvi-from-edm.yaml").write_text(text + "public_repos: [demo]\n")
    common = _hand_written(example)
    root = _checkout(example, tmp_path)
    p = run("validate", "--upstream-root", tmp_path / "none", *common, check=False)
    assert p.returncode == 1 and "no checkout" in p.stdout
    run("validate", "--upstream-root", root, *common)
    rows = {r["pv"]: r["reason"] for r in json.loads((example / "work" / "left-out.json").read_text())["demoHeater"]["demoHeater"]}
    assert rows["$(P):HELP"] == "internal: calc helper"
    assert rows["$(P):NOTSHOWN"] == "not shown, reason not recorded: bo record"
    assert "$(P):SPARE" not in rows


@needs_msi
def test_the_audit_holds_a_hand_written_folder_to_its_classification(example, tmp_path):
    _install_by_hand(example)
    common = _hand_written(example)
    run("validate", "--upstream-root", _checkout(example, tmp_path), *common)
    device = (example / "support" / "demoHeater" / "demoHeater.pvi.device.yaml").read_text()
    pv = next(ln.split(": ", 1)[1] for ln in device.splitlines() if ln.strip().startswith("write_pv:"))
    (example / "classification.yaml").write_text(yaml.safe_dump([dict(module="demoHeater", entity="controller", pv=pv, evidence="hand-written", judged="hand-written", names_only=False, behind_dialog=False, **{"class": "dangerous"})]))
    p = run("audit", *common, check=False)
    assert p.returncode == 1, p.stdout
    assert pv in json.dumps(json.loads((example / "work" / "audit.json").read_text())["protected"]["writable_elsewhere"])


def test_generate_refuses_a_hand_written_folder(example):
    text = (example / "pvi-from-edm.yaml").read_text()
    (example / "pvi-from-edm.yaml").write_text(text + "hand_written: [{repo: demo, folder: demoHeater}]\n")
    p = run("generate", "demoHeater", *_common(example), check=False)
    assert p.returncode != 0 and "written by hand" in p.stderr


def test_check_and_sweep_name_the_hand_written_folders_they_skip(example):
    text = (example / "pvi-from-edm.yaml").read_text()
    (example / "pvi-from-edm.yaml").write_text(text + "hand_written: [{repo: demo, folder: demoHeater}]\n")
    common = _common(example)
    assert "written by hand, skipped: demoHeater" in run("sweep", "--dry-run", "--jobs", 1, *common).stdout
    assert "written by hand, skipped: demoHeater" in run("check", *common).stdout
