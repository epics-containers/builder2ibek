"""Sweep every support module without PVI: generate, validate, then install the
result in the support repos, or leave it in the output folder with `dry_run`. Progress
is banked in <status>/sweep-status.json and <status>/log.md.
"""

from __future__ import annotations

import datetime
import json
import multiprocessing
import re
import shutil
import signal
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import yaml  # noqa: E402
from gen import process, screen_files  # noqa: E402
from protect import UNGATED, load_classes  # noqa: E402
from release import has_screens, pick  # noqa: E402
from settings import CFG, Settings, install  # noqa: E402
from validate import definitions_map, validate_stage  # noqa: E402


def status_file() -> Path:
    return CFG.status / "sweep-status.json"


def pinned(folder: str) -> bool:
    """A folder with an override file of its own: its release is fixed there, and it is
    generated with no search, so the sweep does not reset it first."""
    return bool(CFG.overrides) and (CFG.overrides / f"{folder}.yaml").is_file()


def collision_files() -> list[Path]:
    return [p for p in (CFG.collisions, CFG.status / "stem-collisions.json") if p and p.exists()]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


def inventory() -> list[dict]:
    """Every folder of both repos with a support yaml at HEAD."""
    out = []
    for key, repo in CFG.repos.items():
        tracked = git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        by_dir: dict[str, list[str]] = {}
        for t in tracked:
            if "/" in t and not t.startswith("_"):
                d, f = t.split("/", 1)
                by_dir.setdefault(d, []).append(f)
        for d in sorted(by_dir):
            ymls = [f for f in by_dir[d] if f.endswith(".ibek.support.yaml") and "/" not in f]
            if not ymls:
                continue
            y = ymls[0]
            head = git(repo, "show", f"HEAD:{d}/{y}")
            m = re.search(r"^module:\s*(\S+)", head, re.M)
            has = any(f.endswith(".pvi.device.yaml") for f in by_dir[d]) or bool(re.search(r"^\s+pvi:", head, re.M))
            inst = {}
            ins = [f for f in by_dir[d] if f.endswith(".install.yml")]
            if ins:
                inst = yaml.safe_load(git(repo, "show", f"HEAD:{d}/{ins[0]}")) or {}
            out.append(dict(repo=key, dir=d, yaml=y, module=m.group(1) if m else d, has_pvi=has, install=inst))
    return out


def reserved_stems(items: list[dict]) -> dict[str, set[str]]:
    """Device file names already taken by other folders."""
    taken: dict[str, set[str]] = {}
    for key, repo in CFG.repos.items():
        for t in git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines():
            if t.endswith(".pvi.device.yaml") and "/" in t:
                taken.setdefault(Path(t).name.split(".")[0], set()).add(f"{key}/{t.split('/')[0]}")
    for s, r, d in CFG.reserved_stems:
        taken.setdefault(s, set()).add(f"{r}/{d}")
    for r, d in sorted(CFG.hand_written):
        for f in (CFG.repos[r] / d).glob("*.pvi.device.yaml"):
            taken.setdefault(f.name.split(".")[0], set()).add(f"{r}/{d}")
    for p in collision_files():
        for s in json.loads(p.read_text()):
            taken.setdefault(s, set()).add("sweep/*")
    return taken


def reset_folder(repo: Path, folder: str, yaml_name: str):
    """Remove what an earlier sweep run installed: untracked device files and any yaml edit."""
    if any(CFG.repos[r] == repo and d == folder for r, d in CFG.hand_written):
        raise ValueError(f"{folder} is written by hand: the sweep must not reset it")
    tracked = set(git(repo, "ls-tree", "--name-only", "HEAD", f"{folder}/").splitlines())
    for f in (repo / folder).glob("*.pvi.device.yaml"):
        if f"{folder}/{f.name}" not in tracked:
            f.unlink()
    p = repo / folder / yaml_name
    head = git(repo, "show", f"HEAD:{folder}/{yaml_name}")
    if head and p.read_text() != head:
        p.write_text(head)


def run_item(item: dict) -> dict:
    module_key = item["key"]
    st: dict = {k: item[k] for k in ("repo", "dir", "yaml", "module")}
    st["install_version"] = str(item["install"].get("version", ""))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("module timed out")))
    signal.alarm(1200)
    try:
        return _run(item, module_key, st)
    except Exception as e:  # noqa: BLE001
        st.update(status="failed", cls="tool_exception", reason=f"{type(e).__name__}: {e}", where=traceback.format_exc().splitlines()[-3][:200])
        return st
    finally:
        signal.alarm(0)


def _run(item: dict, key: str, st: dict) -> dict:
    repo = CFG.repos[item["repo"]]
    fixed = pinned(item["dir"])
    if not fixed and not item.get("dry_run"):
        reset_folder(repo, item["dir"], item["yaml"])
        twin = CFG.forks.get((item["repo"], item["dir"]))
        if twin:
            reset_folder(CFG.repos[twin[0]], twin[1], item["yaml"])
    if fixed:
        ov = yaml.safe_load((CFG.overrides / f"{item['dir']}.yaml").read_text())
        st.update(release=ov["release"], release_how="pinned by its override")
    else:
        rel, how = pick(item["dir"], item["module"], item["install"])
        st.update(release=str(rel) if rel else None, release_how=how)
        if rel is None:
            st.update(status="failed", cls="no_release", reason=how)
            return st
        ov = dict(repo=item["repo"], release=str(rel), sweep=True)
        extra = CFG.overrides / f"{key}.sweep.yaml" if CFG.overrides else None
        if extra and extra.exists():
            ov.update(yaml.safe_load(extra.read_text()) or {})
    ov.update(dir=item["dir"], yaml=item["yaml"])
    if not fixed:
        twins = {f"{item['repo']}/{item['dir']}"}
        t = CFG.forks.get((item["repo"], item["dir"]))
        if t:
            twins.add(f"{t[0]}/{t[1]}")
        ov["reserved_stems"] = sorted(s for s, who in item["taken"].items() if who - twins)
    failures: dict[str, tuple[str, str]] = {}
    defs = definitions_map()
    outdir = CFG.output / key
    for _ in range(6):
        rep = process(key, False, ov, CFG.output)
        for name, why in rep["entity_failures"].items():
            failures.setdefault(name, ("unmapped_macro", why))
        val = validate_stage(key, ov, outdir, defs)
        (outdir / "validate.json").write_text(json.dumps(val, indent=1, default=str))
        bad = {k: v for k, v in val["entities"].items() if not v.get("ok")}
        if not bad:
            break
        for k, v in bad.items():
            failures[k] = (v.get("cls", "unknown"), v.get("reason", ""))
        ov.setdefault("skip_entities", {}).update({k: f"validation: {v.get('cls')}: {v.get('reason', '')}" for k, v in bad.items()})
    devs = {k: v for k, v in rep["devices"].items() if "error" not in v}
    errs = {k: v["error"] for k, v in rep["devices"].items() if "error" in v}
    st.update(
        entities_no_pvi={n: why for n, why in rep["no_screen"]},
        entity_failures={k: dict(cls=v[0], reason=v[1]) for k, v in failures.items()},
        device_errors=errs,
    )
    written_yaml = (outdir / item["yaml"]).read_text()
    sup = yaml.safe_load(written_yaml)
    used = {em["pvi"]["yaml_path"] for em in sup.get("entity_models") or [] if em.get("pvi")}
    for f in outdir.glob("*.pvi.device.yaml"):
        if f.name not in used:
            f.unlink()
    if fixed:
        same = all(
            (repo / item["dir"] / f.name).exists() and (repo / item["dir"] / f.name).read_bytes() == f.read_bytes()
            for f in [*outdir.glob("*.pvi.device.yaml"), outdir / item["yaml"]]
        )
        st["regenerated_identically"] = same
    if not used:
        if failures:
            st.update(status="failed", cls=sorted({v[0] for v in failures.values()})[0],
                      reason="; ".join(f"{k}: {v[1]}" for k, v in list(failures.items())[:3]))
        elif errs:
            st.update(status="failed", cls="root_screen_unusable", reason="; ".join(errs.values())[:300])
        elif not any((em.get("databases") for em in sup.get("entity_models") or [])):
            st.update(status="skipped", cls="no_database", reason="no entity loads a database")
        elif has_screens(Path(ov["release"])):
            st.update(status="failed", cls="no_screen_match",
                      reason=f"{len(screen_files(Path(ov['release'])))} screens in the release, none addresses an entity's records")
        else:
            st.update(status="skipped", cls="no_device_screen", reason="the release has no EDM screen")
        return st
    if val["yaml_purity"]:
        st.update(status="failed", cls="yaml_changed", reason=val["yaml_purity"])
        return st
    if val["hygiene"]:
        st.update(status="failed", cls="public_hygiene", reason="; ".join(val["hygiene"][:3]))
        return st
    targets = [(repo / item["dir"])]
    t = CFG.forks.get((item["repo"], item["dir"]))
    if t:
        targets.append(CFG.repos[t[0]] / t[1])
    for tgt in [] if item.get("dry_run") else targets:
        for f in outdir.glob("*.pvi.device.yaml"):
            shutil.copy(f, tgt / f.name)
        (tgt / item["yaml"]).write_text(written_yaml)
    entities = [em["name"] for em in sup.get("entity_models") or [] if em.get("pvi")]
    rows = [v for v in devs.values() if v.get("file_stem", "") + ".pvi.device.yaml" in used]
    st.update(
        status="done",
        cls="validated",
        entities=entities,
        devices=[v.get("file_stem") for v in rows],
        records=sum(v["n_records"] for v in rows),
        placed=sum(v["n_placed"] for v in rows),
        left_out=sum(len(v["left_out"]) for v in rows),
        screen_only=sum(len(v["on_screen_not_in_db"]) for v in rows),
        gated=sum(len(v["gated"]) for v in rows),
        protected=sum(len(v["protected"]) for v in rows),
        field_pvs=sum(len(v["field_pvs"]) for v in rows),
        fields_left=sum(len(v["fields_left"]) for v in rows),
        protected_unlisted=sorted({p for v in rows for p in v["protected_unlisted"]}),
        merged_buttons=sum(len(v["merged_buttons"]) for v in rows),
        dialogs=sum(1 for v in rows for d in v["dialogs"] if d["kind"] == "confirmation_dialog"),
        judgements=sum(len(v["judgements"]) for v in rows),
        how=sorted({v["how"] for v in rows}),
        expanders=sorted({v.get("expander", "?") for v in val["entities"].values() if v.get("ok")}),
        generate_agree=all(v.get("generate_matches_generate2") for v in val["entities"].values() if v.get("ok")),
        n_signals=sum(v.get("n_pvi_signals", 0) for v in val["entities"].values() if v.get("ok")),
    )
    return st


def finish(status: dict):
    """Files derived from all reports: gated writes and left-out PVs."""
    gated = []
    left = {}
    for key, st in status.items():
        p = CFG.output / key / "report.json"
        if not p.exists() or st.get("status") in ("has_pvi", "hand_written", None):
            continue
        rep = json.loads(p.read_text())
        written = st.get("status") == "done"
        for stem, d in rep["devices"].items():
            if "error" in d:
                continue
            for g in d.get("gated", []):
                gated.append(dict(kind="visibility_gated_write", module=st["dir"], repo=st["repo"], entity=d["entity"], pv=g["pv"],
                                  field=g["field"], screen=g["screen"], gate_pv=g["gate_pv"], condition=g["condition"],
                                  widget=g["widget"], handled=g["handled"], written=written))
            for c in d.get("dialogs", []):
                gated.append(dict(kind=c["kind"], module=st["dir"], repo=st["repo"], entity=d["entity"], pv=c["pv"], screen=c["screen"],
                                  dialog=c["dialog"], text=c["text"], gate_pv="", condition="", handled=c["handled"], written=written))
            if written and d["left_out"]:
                left.setdefault(st["dir"], {})[stem] = [x[0] for x in d["left_out"]]
    (CFG.status / "gated-writes.json").write_text(json.dumps(gated, indent=1))
    (CFG.status / "device-refs.json").write_text(json.dumps(device_refs(status), indent=1))
    (CFG.status / "left-out.json").write_text(json.dumps(left, indent=1))
    report_stale(gated)


def report_stale(gated: list[dict]):
    """Entries of the classification file that no longer match a gated write or a dialog."""
    known = {(g["module"], g["entity"], p.strip()) for g in gated for p in g["pv"].split(",")}
    hand = {folder for _, folder in CFG.hand_written}
    stale = sorted(k for k, e in load_classes().items() if k not in known and e["class"] not in UNGATED and k[0] not in hand)
    if stale:
        print(f"classification file: {len(stale)} entries match nothing, e.g. {stale[:3]}", flush=True)


def device_refs(status: dict) -> list[dict]:
    """DeviceRef buttons of written modules, with what their target needs and gets."""
    out = []
    for key, st in status.items():
        if st.get("status") != "done":
            continue
        folder = CFG.output / key
        macros: dict[str, set] = {}
        for f in folder.glob("*.pvi.device.yaml"):
            macros[f.name.split(".")[0]] = set(re.findall(r"\$\((\w+)\)", " ".join(re.findall(r"_pv: (.*)", f.read_text()))))

        def walk(tree):
            for c in tree:
                if c.get("type") == "Group":
                    yield from walk(c["children"])
                elif c.get("type") == "DeviceRef":
                    yield c

        for f in folder.glob("*.pvi.device.yaml"):
            for c in walk(yaml.safe_load(f.read_text()).get("children", [])):
                tgt = c["ui"].split(".")[0]
                passed = set((c.get("macros") or {}))
                out.append(dict(module=st["dir"], device=f.name.split(".")[0], name=c["name"], target=tgt,
                                target_in_module=tgt in macros, macros_missing=sorted(macros.get(tgt, set()) - passed)))
    return out


def log(line: str):
    with (CFG.status / "log.md").open("a") as f:
        f.write(f"{datetime.date.today()} {line}\n")


def init_worker(settings: Settings):
    install(settings)


def sweep(folders: list[str], jobs: int = 12, dry_run: bool = False):
    """`folders` narrows the run; with `dry_run` no support repo is written."""
    CFG.status.mkdir(parents=True, exist_ok=True)
    CFG.output.mkdir(parents=True, exist_ok=True)
    items = inventory()
    taken = reserved_stems(items)
    status_path = status_file()
    status = json.loads(status_path.read_text()) if status_path.exists() and folders else {}
    twins = CFG.fork_twins()
    todo = []
    for it in items:
        it["key"] = it["dir"]
        it["dry_run"] = dry_run
        where = (it["repo"], it["dir"])
        if where in CFG.hand_written:
            status[it["dir"]] = dict(repo=it["repo"], dir=it["dir"], yaml=it["yaml"], module=it["module"], status="hand_written")
            continue
        if where in twins:
            status[it["dir"]] = dict(repo=it["repo"], dir=it["dir"], yaml=it["yaml"], module=it["module"], status="fork_twin", twin_of=twins[where][1])
            continue
        if it["has_pvi"] and not pinned(it["dir"]):
            status[it["dir"]] = dict(repo=it["repo"], dir=it["dir"], status="has_pvi")
            continue
        it["taken"] = taken
        if not folders or it["dir"] in folders:
            todo.append(it)
    log(f"sweep run: {len(todo)} folders" + (" (dry run)" if dry_run else ""))
    with multiprocessing.Pool(jobs, initializer=init_worker, initargs=(CFG,)) as pool:
        for st in pool.imap_unordered(run_item, todo):
            status[st["dir"]] = st
            status_path.write_text(json.dumps(status, indent=1, default=str))
            line = f"{st['dir']} {st.get('status')} {st.get('cls', '')} {st.get('placed', '')}/{st.get('records', '')} {st.get('reason', '')[:120]}"
            log(line)
            print(line, flush=True)
    for it in items:
        where = (it["repo"], it["dir"])
        if where in twins:
            main_st = status.get(twins[where][1], {})
            status[it["dir"]].update(fork_status=main_st.get("status"))
    status_path.write_text(json.dumps(status, indent=1, default=str))
    finish(status)
    if CFG.hand_written:
        print(f"written by hand, skipped: {', '.join(sorted(d for _, d in CFG.hand_written))}", flush=True)
    if not folders:
        check_collisions()


def check_collisions():
    """Device names shared by unrelated folders overwrite each other in one generic IOC."""
    who: dict[str, list[str]] = {}
    twins = {f"{a}/{b}": f"{c}/{d}" for (c, d), (a, b) in CFG.forks.items()}
    for key, repo in CFG.repos.items():
        for f in repo.glob("*/*.pvi.device.yaml"):
            where = f"{key}/{f.parent.name}"
            who.setdefault(f.name.split(".")[0], []).append(twins.get(where, where))
    clash = {k: sorted(set(v)) for k, v in who.items() if len(set(v)) > 1}
    old = {s for p in collision_files() for s in json.loads(p.read_text())}
    (CFG.status / "stem-collisions.json").write_text(json.dumps(sorted(old | set(clash)), indent=1))
    print("device name collisions:", clash, flush=True)


def changed_in_repo(repo: Path) -> list[str]:
    """Paths git sees as changed or new, leaving out folders that start `_`."""
    raw = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "-z", "-uall"], capture_output=True, text=True, check=True).stdout
    paths = [entry[3:] for entry in raw.split("\0") if entry]
    return [p for p in paths if not p.startswith("_")]


def check() -> int:
    """Byte for byte: what a sweep left in the output folder, against the support repos,
    and anything changed in a repo that the sweep did not produce. Reads the repos only."""
    status = json.loads(status_file().read_text())
    compared, different, produced = 0, [], set()
    for key, st in status.items():
        if st.get("status") != "done":
            continue
        outdir = CFG.output / key
        targets = [(st["repo"], st["dir"])]
        if t := CFG.forks.get((st["repo"], st["dir"])):
            targets.append(t)
        for f in [*sorted(outdir.glob("*.pvi.device.yaml")), outdir / st["yaml"]]:
            for repo_key, folder in targets:
                compared += 1
                produced.add((repo_key, f"{folder}/{f.name}"))
                there = CFG.repos[repo_key] / folder / f.name
                if not there.exists():
                    different.append(f"missing from the repo: {repo_key}/{folder}/{f.name}")
                elif there.read_bytes() != f.read_bytes():
                    different.append(f"differs: {repo_key}/{folder}/{f.name}")
    extra = []
    hand = 0
    for repo_key, repo in CFG.repos.items():
        for p in changed_in_repo(repo):
            if (repo_key, p.split("/", 1)[0]) in CFG.hand_written:
                hand += 1
            elif (repo_key, p) not in produced:
                extra.append(f"changed in the repo, not by the sweep: {repo_key}/{p}")
    for line in different + extra:
        print(line)
    if CFG.hand_written:
        print(f"written by hand, skipped: {', '.join(sorted(d for _, d in CFG.hand_written))}")
    print(f"compared {compared} files: {len(different)} different; {len(extra)} changed in a repo but not produced; {hand} changed in hand-written folders, not compared")
    return 1 if different or extra else 0
