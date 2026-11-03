#!/usr/bin/env python3
"""Generate PVI device files and `pvi:` sections for ibek support modules from their EDM
screens. See README.md beside this file."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import settings  # noqa: E402
from settings import CFG, Settings  # noqa: E402

DEFAULT_WORK_DIR = "pvi-from-edm-work"


def common_options() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("where things are (each overrides --config)")
    g.add_argument("--config", type=Path, help="YAML settings file: see README.md")
    g.add_argument("--repo", action="append", default=[], metavar="[KEY=]FOLDER", help="support repo folder, repeatable; its key defaults to the folder name")
    g.add_argument("--prod-root", action="append", type=Path, help="released support root, repeatable, in order of preference")
    g.add_argument("--work-root", action="append", type=Path, help="unreleased support root, repeatable")
    g.add_argument("--older-root", action="append", type=Path, help="older released support root, repeatable, tried last")
    g.add_argument("--msi", type=Path, help="msi executable; falls back to one on PATH")
    g.add_argument("--base-dbd", type=Path, help="EPICS base dbd folder")
    g.add_argument("--support-dbd-glob", help="glob for a record type's dbd in any support module, with {} for the type")
    g.add_argument("--edm-colors", type=Path, help="EDM colors.list, for the review pages")
    g.add_argument("--classification", type=Path, help="classification file; with none, every gated write counts as unsure")
    g.add_argument("--classify-rules", type=Path, help="rules judged by reading, for the classify subcommand")
    g.add_argument("--overrides", type=Path, help="overrides folder")
    g.add_argument("--collisions", type=Path, help="JSON list of device file names no sweep may use")
    g.add_argument("--work-dir", type=Path, help=f"parent of the folders below, default ./{DEFAULT_WORK_DIR}")
    g.add_argument("--output-dir", type=Path, help="generated files, default <work-dir>/out")
    g.add_argument("--sandbox-dir", type=Path, help="test IOC instances and .bob files, default <work-dir>/sandbox")
    g.add_argument("--review-dir", type=Path, help="review pages, default <work-dir>/review")
    g.add_argument("--status-dir", type=Path, help="status files and log, default <work-dir>")
    return p


def configure(a: argparse.Namespace) -> Settings:
    s = settings.from_file(a.config) if a.config else Settings()
    for item in a.repo:
        key, eq, folder = item.partition("=")
        if not eq:
            key, folder = Path(item).name, item
        s.repos[key] = Path(folder)
    for attr, arg in (("prod", a.prod_root), ("work", a.work_root), ("older", a.older_root)):
        if arg:
            setattr(s, attr, arg)
    for name in ("msi", "base_dbd", "support_dbd_glob", "edm_colors", "classification", "classify_rules", "overrides", "collisions"):
        if getattr(a, name) is not None:
            setattr(s, name, getattr(a, name))
    work = a.work_dir or Path(DEFAULT_WORK_DIR)
    s.output = a.output_dir or work / "out"
    s.sandbox = a.sandbox_dir or work / "sandbox"
    s.review = a.review_dir or work / "review"
    s.status = a.status_dir or work
    s.repos = {k: v.resolve() for k, v in s.repos.items()}
    for name in ("output", "sandbox", "review", "status", "base_dbd", "edm_colors", "classification", "classify_rules", "overrides", "collisions"):
        if getattr(s, name) is not None:
            setattr(s, name, getattr(s, name).resolve())
    s.prod, s.work, s.older = [[p.resolve() for p in roots] for roots in (s.prod, s.work, s.older)]
    if unknown := [k for k in s.public_repos | {r for r, _ in s.hand_written} | {r for k in s.forks.items() for r, _ in k} if s.repos and k not in s.repos]:
        raise SystemExit(f"settings name a repo not given with --repo: {sorted(unknown)}")
    return s


def need_repos():
    if not CFG.repos:
        raise SystemExit("no support repo: give --repo, or `repos` in --config")
    for key, folder in CFG.repos.items():
        top = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
        if not top or Path(top).resolve() != folder:
            raise SystemExit(f"repo {key}: {folder} is not the top of a git checkout: an empty submodule?")
    if CFG.classification and not CFG.classification.exists():
        raise SystemExit(f"classification file not found: {CFG.classification}")


def cmd_sweep(a) -> int:
    from sweep import sweep

    need_repos()
    sweep(a.folders, a.jobs, a.dry_run)
    return 0


def cmd_check(a) -> int:
    from sweep import check

    need_repos()
    return check()


def cmd_generate(a) -> int:
    from gen import generate

    need_repos()
    if not CFG.overrides:
        raise SystemExit("generate works from <overrides>/<module>.yaml: give --overrides; for the rest use sweep")
    generate(a.modules, a.write)
    return 0


def cmd_validate(a) -> int:
    from validate import definitions_map, validate_stage

    need_repos()
    status = json.loads((CFG.status / "sweep-status.json").read_text())
    defs = definitions_map()
    bad = 0
    for key, st in status.items():
        if st.get("status") != "done" or (a.folders and st["dir"] not in a.folders):
            continue
        rep = json.loads((CFG.output / key / "report.json").read_text())
        ov = dict(repo=rep["repo"], dir=rep["folder"], yaml=rep["yaml"], release=rep["release"])
        val = validate_stage(key, ov, CFG.output / key, defs)
        (CFG.output / key / "validate.json").write_text(json.dumps(val, indent=1, default=str))
        failed = {k: v.get("cls") for k, v in val["entities"].items() if not v.get("ok")}
        problems = [*([val["yaml_purity"]] if val["yaml_purity"] else []), *val["hygiene"][:3]]
        bad += bool(failed or problems)
        print(f"{key}: {len(val['ok_entities'])} of {len(val['entities'])} entities pass {failed or ''} {problems or ''}".rstrip(), flush=True)
    return 1 if bad else 0


def cmd_audit(a) -> int:
    import audit

    return audit.main()


def cmd_evidence(a) -> int:
    import evidence

    evidence.main()
    return 0


def cmd_classify(a) -> int:
    import classify

    classify.main(a.out.resolve() if a.out else None)
    return 0


def cmd_review(a) -> int:
    import classify
    import render

    render.review(a.modules)
    classify.write_review()
    print(CFG.review / "index.html")
    return 0


def cmd_survey(a) -> int:
    from survey import survey

    need_repos()
    CFG.status.mkdir(parents=True, exist_ok=True)
    survey(a.folders)
    return 0


def cmd_dump_edl(a) -> int:
    from edl import as_list, links, parse_edl, pv_uses, text_of

    for f in a.files:
        s = parse_edl(f)
        print(f"=== {f.name} {s.w}x{s.h} title={s.title!r} objs={len(s.objects)}")
        for o in sorted(s.objects, key=lambda o: (o.y, o.x)):
            d = ""
            if o.cls == "activeXTextClass":
                d = repr(text_of(o))
                if o.get("visPv"):
                    d += f" vis={o.get('visPv')}"
            elif o.cls == "activeRectangleClass":
                d = "fill" if o.get("fill") else "line"
                if o.get("invisible"):
                    d += " invis"
            if uses := pv_uses(o):
                d += " " + " ".join(f"{u.role}:{u.pv}" for u in uses)
            for ln in links(o):
                d += f" [{ln['kind']} {ln['file']} {ln['label']!r} {ln['symbols']!r}]"
            if o.get("press_value") or o.get("pressValue"):
                d += f" press={o.get('pressValue')} rel={o.get('releaseValue')} onLabel={o.get('onLabel')}"
            if o.cls == "shellCmdClass":
                d += f" cmd={as_list(o.get('command'))[:1]}"
            print(f"{o.y:5d} {o.x:5d} {o.w:4d}x{o.h:<4d} {o.cls.replace('Class', ''):26s} {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = common_options()
    ap = argparse.ArgumentParser(prog="pvi_from_edm.py", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, func, text):
        p = sub.add_parser(name, parents=[common], help=text, description=text)
        p.set_defaults(func=func)
        return p

    p = add("sweep", cmd_sweep, "generate and validate every support module without PVI, and install the result in the support repos")
    p.add_argument("folders", nargs="*", help="only these module folders")
    p.add_argument("--jobs", type=int, default=12)
    p.add_argument("--dry-run", action="store_true", help="write nothing to a support repo: results stay in the output folder")
    add("check", cmd_check, "compare the output of a sweep with the support repos, byte for byte; exit 1 on a difference")
    p = add("generate", cmd_generate, "one module with an override file of its own")
    p.add_argument("modules", nargs="+")
    p.add_argument("--write", action="store_true", help="also write to its support repo")
    p = add("validate", cmd_validate, "validate again what a sweep generated")
    p.add_argument("folders", nargs="*", help="only these module folders")
    add("audit", cmd_audit, "check the output of a sweep against the EDM screens and the .bob files; exit 1 on a failure")
    add("evidence", cmd_evidence, "gather the facts on each gated write, for classify")
    p = add("classify", cmd_classify, "write the classification file from the evidence; entries judged by a person stay")
    p.add_argument("--out", type=Path, help="write here and leave the classification file as it is")
    p = add("review", cmd_review, "write review pages: each EDM screen beside its generated .bob")
    p.add_argument("modules", nargs="*", help="only these module folders")
    p = add("survey", cmd_survey, "estimate a sweep: no validation, nothing written to a repo")
    p.add_argument("folders", nargs="*", help="only these module folders")
    p = add("dump-edl", cmd_dump_edl, "print EDM screens as rows sorted by coordinates")
    p.add_argument("files", nargs="+", type=Path)

    a = ap.parse_args(argv)
    settings.install(configure(a))
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
