#!/usr/bin/env python3
"""Build the sweep's candidate set from /dls_sw/prod.

Seeds from modules that carry a `.proto` / `.protocol` anywhere in their latest
release, rather than sweeping all ~750 modules and rejecting most of them.

Also applies the case-duplicate rule: /dls_sw/prod holds pairs of modules
differing only in case, left behind when DLS renamed a module. Two folders
differing only in case collide on a case-insensitive clone of
ibek-runtime-streamdevice, and `ibek pattern add` resolves a pattern by
`clone_dir / name`, so it would silently pick up whichever landed.

Writes candidates.json (full detail) and prints a TSV summary.

usage: scan-candidates.py [-o OUTDIR] [--prod /dls_sw/prod]

Takes ~3 minutes: it walks the latest release of every module.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

PROTO_SUFFIXES = (".proto", ".protocol")
WALK_MAX_DEPTH = 3

# DLS version strings are not sortable by `sort -V` and not comparable as
# strings: `1-2` and `1.0` and `2-1-1` and `2-0beta1` and `1-2-1dls3` all occur.
# Parse them into comparable tuples instead. Separators are `-`, `.` and `_`;
# within a chunk, digit runs compare numerically and letter runs are ranked
# either side of the bare version:
#
#   1-2 < 1-10          numeric, not lexical
#   2-1 < 2-1-1         a longer version wins when the prefix is equal
#   2-0beta1 < 2-0      a pre-release loses to the release
#   1-2-1 < 1-2-1dls3   a DLS patch of an upstream release wins
#   2.9 < 2-13          `.` and `-` are the same separator
#   Rx-y < 1-0          a name with no leading number is not a release at all:
#                       `Rx-y` is the DLS build scratch directory (it holds the
#                       build logs of whichever release was last built) and 48
#                       modules under /dls_sw/prod have one. Same for the branch
#                       builds `maketest`, `os_independant_test`, `b16-4`. None
#                       of them may ever be picked over a numbered release.
PRE_RELEASE = {"beta", "alpha", "rc", "pre", "dev", "snapshot"}
_SEGMENT = re.compile(r"(\d+)|(\D+)")
_PRE, _NUM, _BARE, _POST = 0, 1, 2, 3


def version_key(version: str) -> tuple:
    """Order DLS version strings. See the table above for the conventions."""
    key: list[tuple[int, int, str]] = []
    seen_number = False
    for chunk in re.split(r"[-._]+", version):
        if not chunk:
            continue
        for num, text in _SEGMENT.findall(chunk):
            if num:
                key.append((_NUM, int(num), ""))
                seen_number = True
            else:
                word = text.lower()
                # Letters before any digit are a prefix, not a suffix, and rank
                # the whole string below every numbered release.
                rank = _PRE if word in PRE_RELEASE or not seen_number else _POST
                key.append((rank, 0, word))
        key.append((_BARE, 0, ""))  # end of chunk: 2-1 < 2-1-1, 2-0beta1 < 2-0
    return tuple(key)


def tree_key(name: str) -> tuple:
    """Order the /dls_sw/prod/R* EPICS trees: R3.14.8.2 < R3.14.11 < R7.0.7.

    Derived from the directory name rather than a hardcoded list, so a tree DLS
    adds later ranks correctly without editing this script.
    """
    return version_key(name)


def collect_releases(prod: Path) -> dict[str, list[dict]]:
    """module name -> every release directory, across every EPICS tree."""
    mods: dict[str, list[dict]] = collections.defaultdict(list)
    for tree in sorted(prod.glob("R*")):
        support = tree / "support"
        if not support.is_dir():
            continue
        for mod in sorted(support.iterdir()):
            if not mod.is_dir():
                continue
            for ver in sorted(mod.iterdir()):
                if not ver.is_dir():
                    continue
                try:
                    mtime = ver.stat().st_mtime
                except OSError:
                    continue
                mods[mod.name].append(
                    {
                        "tree": tree.name,
                        "version": ver.name,
                        "path": str(ver),
                        "mtime": mtime,
                        "date": time.strftime("%Y-%m-%d", time.localtime(mtime)),
                    }
                )
    return mods


def latest(releases: list[dict]) -> dict:
    """The module's latest release: newest EPICS tree, then highest version.

    Not the newest mtime. A back-port rebuilt after the release that supersedes
    it has the newer mtime but is the older code: `keithley6517B 1-1-1` was
    rebuilt under `R3.14.12.3` in 2019, four months after `1-2` was built under
    `R3.14.12.7`. Same for `ETLdetector` (`1-20-1` rebuilt five minutes after
    `1-21`) and `ametekLockIn` (`1-6special2` after `1-17special2`).

    Not a plain version sort either, because version numbers restart: `fw102`
    was recreated as a lowercase module in 2023 and began again at `1.0`, so its
    highest version anywhere is a `2-2` built in 2015 under an EPICS tree it has
    since left. Picking the newest tree the module appears in first is what
    makes the version comparison meaningful, and it is the rule the
    vdct-conversion skill documents.

    mtime survives only as the tie-break, for the case of one version built
    twice in the same tree.
    """
    top = max(tree_key(r["tree"]) for r in releases)
    in_top = [r for r in releases if tree_key(r["tree"]) == top]
    return max(in_top, key=lambda r: (version_key(r["version"]), r["mtime"]))


def describe(name: str, releases: list[dict]) -> str:
    """`fw102: 9 release(s), newest build 2-1 (2025-07-17)`.

    The case-duplicate evidence, so this reports the most recently *built*
    release - "is this copy still alive?" - rather than latest()'s pick, which
    answers the different question of which release to convert from.
    """
    tip = max(releases, key=lambda r: r["mtime"])
    count = len({r["version"] for r in releases})
    return f"{name}: {count} release(s), newest build {tip['version']} ({tip['date']})"


def resolve_case_duplicates(mods: dict[str, list[dict]]) -> tuple[set[str], list[dict]]:
    """Return (dropped module names, skip-report rows).

    Rule: when two modules share a name under tolower(), keep the one with more
    releases and the later latest release; drop the other. Decide on release
    evidence, not on case - lowercase winning is a consequence of the DLS
    convention, not the rule.
    """
    by_lower: dict[str, list[str]] = collections.defaultdict(list)
    for name in mods:
        by_lower[name.lower()].append(name)

    dropped: set[str] = set()
    rows: list[dict] = []
    for names in [v for _, v in sorted(by_lower.items())]:
        if len(names) < 2:
            continue
        scored = sorted(
            names,
            key=lambda n: (
                len({r["version"] for r in mods[n]}),
                # "the later latest release" - the most recent build of any of
                # its releases, which is the signal the issue's evidence table
                # describes. Not latest()'s pick, which is about which release
                # to convert from, not about which copy is alive.
                max(r["mtime"] for r in mods[n]),
            ),
            reverse=True,
        )
        winner, losers = scored[0], scored[1:]
        for loser in losers:
            dropped.add(loser)
            # The rename fingerprint: the abandoned copy's only release shares
            # its number AND its date with one of the winner's. Report whether
            # it is present - its absence means two independent histories that
            # merely collide on case (still a collision, still dropped).
            win_by_ver = {r["version"]: r["date"] for r in mods[winner] if r["date"]}
            shared = [
                f"{r['version']}@{r['date']}"
                for r in mods[loser]
                if win_by_ver.get(r["version"]) == r["date"]
            ]
            evidence = (
                f"; shared release {', '.join(shared)} - the rename"
                if shared
                else "; no shared release/date - independent histories"
            )
            rows.append(
                {
                    "module": loser,
                    "reason": "case-duplicate",
                    "detail": (
                        f"collides with {winner} under tolower(); "
                        + describe(loser, mods[loser])
                        + " vs "
                        + describe(winner, mods[winner])
                        + evidence
                    ),
                }
            )
    return dropped, rows


def find_protocols(root: str) -> list[str]:
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git" and not d.startswith("O.")]
        if dirpath[len(root) :].count(os.sep) >= WALK_MAX_DEPTH:
            dirnames[:] = []
        for f in filenames:
            if f.endswith(PROTO_SUFFIXES):
                hits.append(os.path.relpath(os.path.join(dirpath, f), root))
    return sorted(hits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--outdir", default=".", type=Path)
    ap.add_argument("--prod", default="/dls_sw/prod", type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    mods = collect_releases(args.prod)
    print(f"modules in {args.prod}: {len(mods)}", file=sys.stderr)

    dropped, dup_rows = resolve_case_duplicates(mods)
    for row in dup_rows:
        print(
            f"case-duplicate: drop {row['module']} - {row['detail']}", file=sys.stderr
        )

    candidates = []
    for name in sorted(mods):
        if name in dropped:
            continue
        rel = latest(mods[name])
        protos = find_protocols(rel["path"])
        if not protos:
            continue
        candidates.append(
            {
                "name": name,
                "tree": rel["tree"],
                "version": rel["version"],
                "path": rel["path"],
                "date": rel["date"],
                "protocols": protos,
                "releases": sorted(
                    ({r["version"] for r in mods[name]}),
                ),
            }
        )

    (args.outdir / "candidates.json").write_text(json.dumps(candidates, indent=1))
    (args.outdir / "case-duplicates.json").write_text(json.dumps(dup_rows, indent=1))
    print(
        f"candidates: {len(candidates)} (case-duplicates dropped: {len(dropped)})",
        file=sys.stderr,
    )
    print("module\ttree\tversion\tdate\tprotocols")
    for c in candidates:
        print(
            f"{c['name']}\t{c['tree']}\t{c['version']}\t{c['date']}\t{len(c['protocols'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
