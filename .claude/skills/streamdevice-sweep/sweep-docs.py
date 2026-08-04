#!/usr/bin/env python3
"""Plan (and optionally apply) the documentation sweep for one support module.

Docs live in a `docs/` subfolder of the pattern and are NEVER vendored into an
IOC instance - they are repo context. Which is why a pattern that gains a
`docs/` folder also gains an `ibek.manifest.yaml`, and a pattern that does not
keeps neither.

Sweep set: `README*` and `*.txt` at the module root, plus `documentation/`,
`docs/`, `doc/`.

usage:
    sweep-docs.py --module /dls_sw/prod/R3.14.12.7/support/lakeshore340/2-6
    sweep-docs.py --module <dir> --pattern <repo>/lakeshore340 --apply

Plan mode prints one line per file with its action, reason and the `docs/` name
it would be written to, and writes docs-plan.json. `--apply` converts, writes
`<pattern>/docs/`, prunes the docs it wrote for an earlier release, and adds or
removes `<pattern>/ibek.manifest.yaml` to match.

Needs pandoc only when the plan actually contains something to convert - a
pattern whose docs are all plain markdown, and a re-sweep that only has a stale
manifest to remove, both run without it. pandoc is taken from $PANDOC, then
PATH, then whatever `pypandoc_binary` ships; see resolve_pandoc.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

PANDOC_MISSING = (
    "pandoc not found. Install it (`apt-get install -y pandoc`), or point $PANDOC "
    "at a binary, or run this script under `uv run --with pypandoc_binary`, which "
    "is what works in the epics-containers dev container."
)

# --- the copyright blocklist -------------------------------------------------
# ibek-runtime-streamdevice is PUBLIC. DLS documentation folders routinely hold
# manufacturer datasheets and manuals that DLS has no right to redistribute.
# Two arms: what a file IS, and where it LIVES.

BLOCKED_EXT = {
    # the issue's list
    ".pdf",
    ".doc",
    ".zip",
    # same class of thing
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".xls",
    ".ppt",
    ".vsd",
    ".dwg",
    ".exe",
    ".jar",
    ".bin",
    # figures - stripped from converted docs, never copied
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
    ".ico",
    ".eps",
    ".ps",
}

# A path segment (case-insensitive) that means "third-party material". `private`
# and `manufacturer` are live DLS conventions - lakeshore340 keeps its vendor
# manuals in documentation/private/Manufacturer/, mks647c in
# documentation/manufacturer/.
BLOCKED_DIRS = {
    "private",
    "manufacturer",
    "manufacturers",
    "vendor",
    "supplier",
    "datasheet",
    "datasheets",
    "manual",
    "manuals",
    "3rdparty",
    "third-party",
}

# Build output and VCS spoil, never authored content.
GENERATED_DIRS = {
    "doxygen",
    "html",
    "latex",
    "search",
    "_build",
    "build",
    ".svn",
    ".git",
    "o.common",
    "o.linux-x86_64",
}

# Noise that is authored but says nothing about the device or its protocol.
NOISE_NAMES = re.compile(
    r"^(makefile|\.gitignore|license(\.txt)?|copying|changelog(\.txt)?|"
    r"devhistory\.txt|cmakelists\.txt|\.project|\.cproject)$",
    re.I,
)

PANDOC_FORMAT = {
    ".html": "html",
    ".htm": "html",
    ".rst": "rst",
    ".odt": "odt",
    ".docx": "docx",
    ".tex": "latex",
}

VERBATIM = {".md", ".markdown"}
# Read and curate by hand: plain text, Doxygen source pages, extension-less
# authored docs. "Curate, don't dump" - a machine cannot tell a device
# description from a build instruction.
MANUAL = {".txt", ".dox", ".src", ""}

REDIRECT = re.compile(r"http-equiv\s*=\s*[\"']?refresh", re.I)
MIN_USEFUL_BYTES = 80

# Markdown is copied rather than converted, so pandoc's image filter never sees
# it - and a `![fig](fig.png)` that survives into the pattern is a broken link in
# a public repo, pointing at artwork that was deliberately not copied. Markdown
# that embeds figures therefore goes through pandoc too.
MD_IMAGE = re.compile(r"!\[[^\]]*\]\(|<img\b", re.I)
VERBATIM_PLAIN = "markdown"
VERBATIM_FIGURES = "markdown with figures"

# The folder names that are stripped from a doc's `docs/` filename.
DOC_DIRS = ("documentation", "docs", "doc")


def classify(module_dir: Path, path: Path) -> tuple[str, str]:
    """Return (action, reason). action in {convert, verbatim, manual, blocked, skip}."""
    rel = path.relative_to(module_dir)
    parts = [p.lower() for p in rel.parts[:-1]]
    ext = path.suffix.lower()

    for p in parts:
        if p in BLOCKED_DIRS:
            return "blocked", f"under a '{p}/' folder - third-party material"
        if p in GENERATED_DIRS:
            return "skip", f"under a generated/VCS folder '{p}/'"
    if ext in BLOCKED_EXT:
        return (
            "blocked",
            f"'{ext}' is on the copyright blocklist - reference it by name instead",
        )
    if NOISE_NAMES.match(path.name):
        return "skip", "build/licence/changelog noise"
    if ext in (".js", ".css", ".cfg", ".sh", ".xsl", ".dtd", ".svn-base"):
        return "skip", f"'{ext}' is tooling, not documentation"

    try:
        size = path.stat().st_size
    except OSError:
        return "skip", "unreadable"
    if size == 0:
        return "skip", "empty file"

    if ext in (".html", ".htm"):
        head = path.read_text(errors="replace")[:2000]
        if REDIRECT.search(head):
            return "skip", "redirect stub to the doxygen index"
    if ext == ".xml":
        head = path.read_text(errors="replace")[:2000]
        if "docbook" in head.lower() or re.search(r"<\s*(article|book)\b", head, re.I):
            return "convert", "DocBook"
        return "manual", "XML of unknown schema"
    if ext in PANDOC_FORMAT:
        return "convert", PANDOC_FORMAT[ext]
    if ext in VERBATIM:
        if size < MIN_USEFUL_BYTES:
            return "skip", f"markdown but only {size} bytes - nothing worth reading"
        if MD_IMAGE.search(path.read_text(errors="replace")):
            return "verbatim", VERBATIM_FIGURES
        return "verbatim", VERBATIM_PLAIN
    if ext in MANUAL:
        if size < MIN_USEFUL_BYTES:
            return "skip", f"only {size} bytes - nothing worth reading"
        return "manual", "read it and decide - keep device/PV/protocol prose only"
    return "skip", f"unhandled extension '{ext}'"


def sweep_set(module_dir: Path) -> list[Path]:
    found: list[Path] = []
    for entry in sorted(module_dir.iterdir()):
        if entry.is_file() and (
            entry.name.lower().startswith("readme") or entry.suffix.lower() == ".txt"
        ):
            found.append(entry)
    for sub in ("documentation", "docs", "doc", "Documentation"):
        d = module_dir / sub
        if not d.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames if x.lower() not in GENERATED_DIRS]
            for f in sorted(filenames):
                found.append(Path(dirpath) / f)
    return found


# `*.pvi.device.yaml` is in the allow-list although issue #115's text does not
# name it: ibek-runtime-streamdevice's README documents it as an optional
# member of a pattern, and the manifest is an allow-list, so leaving it out
# would silently stop vendoring it the day a pattern grows one.
MANIFEST = r"""# This pattern carries files that must NOT be vendored into an IOC
# instance (docs/). The allow-list below is therefore explicit; without it
# ibek vendors every file in the folder.
version: 1
vendor:
  - src: '.*\.(template|proto|protocol|db|req|ibek\.support\.yaml|pvi\.device\.yaml)$'
    dest: config
"""

# Every file this script writes opens with this marker, so a later sweep can
# tell its own output from a document a human curated by hand and prune only
# the former. Do not add it to a hand-written doc.
GENERATED_MARK = "<!-- generated by streamdevice-sweep -->"


def provenance(module: str, release: str, rel: str, source: Path, how: str) -> str:
    """The header block: the generated marker plus the issue's provenance line.

    `how` states only what this script did. It deliberately does not claim the
    build/release/site-configuration sections were dropped - that is curation,
    which happens afterwards and by hand (SKILL.md section 5).
    """
    return (
        f"{GENERATED_MARK}\n\n"
        f"*{how} `{rel}` in DLS support module `{module}` release `{release}` "
        f"(`{source}`).*\n\n"
    )


def _flatten(rel: Path, strip_doc_dir: bool) -> str:
    parts = list(rel.parts)
    if strip_doc_dir and len(parts) > 1 and parts[0].lower() in DOC_DIRS:
        parts = parts[1:]
    stem = Path(parts[-1]).stem or parts[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(parts[:-1] + [stem])) + ".md"


def assign_names(plan: list[dict]) -> dict[str, str]:
    """Map each doc-producing plan item to its `docs/` filename, collision-free.

    A module's root `README.md` and its `documentation/README.md` are different
    documents (`delaygen` ships a synApps pointer and the real DG645 device
    notes respectively), and both reduce to `README.md`. When names collide the
    full relative path is used for all of them, so no document silently
    overwrites another.
    """
    produced = [i for i in plan if i["action"] in ("convert", "verbatim")]
    grouped: dict[str, list[str]] = {}
    for item in produced:
        grouped.setdefault(_flatten(Path(item["file"]), True), []).append(item["file"])

    names: dict[str, str] = {}
    for short, files in grouped.items():
        for f in files:
            names[f] = short if len(files) == 1 else _flatten(Path(f), False)

    # A residual collision would be pathological; number rather than lose a file.
    used: set[str] = set()
    for f in sorted(names):
        name = names[f]
        if name in used:
            base, n = name[:-3], 2
            while f"{base}-{n}.md" in used:
                n += 1
            name = f"{base}-{n}.md"
        names[f] = name
        used.add(name)
    return names


def resolve_pandoc() -> str | None:
    """Locate a pandoc executable, or None if there is not one.

    Prefers $PANDOC, then PATH, then the binary `pypandoc_binary` ships. The
    last of those is how pandoc is reachable in the epics-containers dev
    container, which has no distro pandoc package and no route to install one.
    """
    override = os.environ.get("PANDOC")
    if override:
        return override if Path(override).is_file() else None
    if found := shutil.which("pandoc"):
        return found
    try:
        import pypandoc
    except ImportError:
        return None
    try:
        return pypandoc.get_pandoc_path()
    except OSError:
        return None


def pandoc_to_markdown(src: Path, fmt: str) -> str:
    pandoc = resolve_pandoc()
    if pandoc is None:
        sys.exit(PANDOC_MISSING)
    return subprocess.run(
        [
            pandoc,
            "--from",
            fmt,
            "--to",
            "gfm",
            "--wrap=none",
            "--lua-filter",
            str(HERE / "strip-images.lua"),
            str(src),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def needs_pandoc(plan: list[dict]) -> bool:
    return any(
        i["action"] == "convert"
        or (i["action"] == "verbatim" and i["reason"] == VERBATIM_FIGURES)
        for i in plan
    )


def manifest_vendors_docs(text: str) -> list[str]:
    """The rules in an existing manifest that would vendor a generated doc.

    A manifest this sweep did not write belongs to a human, so it is checked
    rather than replaced - but a rule matching `docs/...` defeats the only
    reason the pattern has a manifest at all.
    """
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [f"unparseable: {exc}"]
    if not isinstance(doc, dict):
        return ["not a mapping"]
    bad = []
    for rule in doc.get("vendor") or []:
        src = rule.get("src") if isinstance(rule, dict) else None
        if not isinstance(src, str):
            continue
        try:
            if re.search(src, "docs/example.md"):
                bad.append(src)
        except re.error:
            bad.append(f"{src} (invalid regex)")
    return bad


def is_generated(f: Path) -> bool:
    """Was this file written by a sweep? Only those may be overwritten or pruned."""
    return f.read_text(errors="replace")[:200].startswith(GENERATED_MARK)


def prune(docs: Path, keep: set[str]) -> None:
    """Remove docs an earlier sweep wrote and this one did not.

    Without this a re-sweep against a newer DLS release leaves the old release's
    documentation in place - attributed by its own provenance line to a release
    the sweep no longer reads - and keeps the manifest alive with it. Only files
    carrying GENERATED_MARK are pruned; a hand-curated document is left alone.
    """
    if not docs.is_dir():
        return
    for f in sorted(docs.iterdir()):
        if not f.is_file() or f.name in keep:
            continue
        if is_generated(f):
            f.unlink()
            print(f"removed stale {f} (not produced by this release's sweep)")
    if not any(docs.iterdir()):
        docs.rmdir()
        print(f"removed empty {docs}")


def apply_plan(
    module_dir: Path, pattern: Path, plan: list[dict], module: str, release: str
) -> None:
    if needs_pandoc(plan) and resolve_pandoc() is None:
        sys.exit(PANDOC_MISSING)
    docs = pattern / "docs"
    names = assign_names(plan)

    # A destination that already exists and is not this script's output is a
    # hand-curated document. prune() never deletes one, but the write loop below
    # would overwrite it before prune ever runs - so the destinations are
    # checked up front and the whole apply refuses rather than half-writing.
    written = [i for i in plan if i["action"] in ("convert", "verbatim")]
    clashes = [
        d
        for d in (docs / names[i["file"]] for i in written)
        if d.exists() and not is_generated(d)
    ]
    if clashes:
        sys.exit(
            "refusing to overwrite hand-curated documentation:\n  "
            + "\n  ".join(str(c) for c in clashes)
            + "\nrename or delete these, or merge the new text by hand."
        )

    produced = 0
    for item in written:
        src = module_dir / item["file"]
        docs.mkdir(parents=True, exist_ok=True)
        dest = docs / names[item["file"]]
        if item["action"] == "convert":
            fmt = "docbook" if item["reason"] == "DocBook" else item["reason"]
            how = "Converted from"
            body = pandoc_to_markdown(src, fmt)
        elif item["reason"] == VERBATIM_FIGURES:
            how = "Converted from"
            body = pandoc_to_markdown(src, "gfm")
        else:
            how = "Copied verbatim from"
            body = src.read_text(errors="replace")
        dest.write_text(
            provenance(module, release, item["file"], module_dir, how) + body
        )
        produced += 1
        print(f"wrote {dest}")

    prune(docs, set(names.values()))

    manifest = pattern / "ibek.manifest.yaml"
    has_docs = docs.is_dir() and any(docs.iterdir())
    if has_docs:
        if not manifest.exists():
            manifest.write_text(MANIFEST)
            print(f"wrote {manifest}")
        elif rules := manifest_vendors_docs(manifest.read_text()):
            print(
                f"WARNING: {manifest} would vendor the generated docs into an IOC "
                "instance - offending rule(s): " + "; ".join(rules),
                file=sys.stderr,
            )
    elif manifest.exists():
        if manifest.read_text() == MANIFEST:
            manifest.unlink()
            print(f"removed {manifest} (nothing left that must not be vendored)")
        else:
            print(
                f"WARNING: left {manifest} alone - it was not written by this sweep "
                "and may carry hand-written vendor rules",
                file=sys.stderr,
            )
    if produced == 0:
        print(
            "no docs produced automatically - anything marked MANUAL still needs "
            "reading and curating by hand",
            file=sys.stderr,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--module", required=True, type=Path, help="DLS release directory")
    ap.add_argument(
        "--pattern", type=Path, help="pattern folder in ibek-runtime-streamdevice"
    )
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument(
        "--skips-json",
        type=Path,
        help="accumulate blocked files here for render-report.py (read-modify-write)",
    )
    args = ap.parse_args()

    module_dir = args.module.resolve()
    release = module_dir.name
    module = module_dir.parent.name

    plan = []
    for path in sweep_set(module_dir):
        action, reason = classify(module_dir, path)
        plan.append(
            {
                "file": str(path.relative_to(module_dir)),
                "action": action,
                "reason": reason,
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        )

    names = assign_names(plan)
    for item in plan:
        item["dest"] = f"docs/{names[item['file']]}" if item["file"] in names else ""
    for item in sorted(plan, key=lambda i: (i["action"], i["file"])):
        note = item["reason"] + (f" -> {item['dest']}" if item["dest"] else "")
        print(f"{item['action'].upper():9s} {item['file']:60s} {note}")

    counts: dict[str, int] = {}
    for item in plan:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    print(
        f"\n{module} {release}: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        file=sys.stderr,
    )
    blocked = [i["file"] for i in plan if i["action"] == "blocked"]
    if blocked:
        print(
            "REPORT THESE AS SKIPS (name + part number, do not copy):\n  "
            + "\n  ".join(blocked),
            file=sys.stderr,
        )

    if args.out:
        args.out.write_text(json.dumps(plan, indent=1))
    if args.skips_json:
        acc = (
            json.loads(args.skips_json.read_text()) if args.skips_json.is_file() else []
        )
        acc = [a for a in acc if a["module"] != module]
        acc += [
            {
                "module": module,
                "release": release,
                "file": i["file"],
                "reason": i["reason"],
            }
            for i in plan
            if i["action"] == "blocked"
        ]
        args.skips_json.write_text(json.dumps(acc, indent=1))
    if args.apply:
        if not args.pattern:
            sys.exit("--apply needs --pattern")
        apply_plan(module_dir, args.pattern, plan, module, release)
    return 0


if __name__ == "__main__":
    sys.exit(main())
