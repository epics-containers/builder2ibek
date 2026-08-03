#!/usr/bin/env python3
"""Flag `*.ibek.support.yaml` descriptions that are missing, empty or trivial.

The sweep deliberately generates no per-pattern README describing the entity
models - the support yaml is meant to be self-documenting. That only holds if
the descriptions are real, so this audit is the other half of that decision. Its
output goes in the sweep report next to the skips.

A description is flagged when it is:
  missing / empty       no `description:` key, or blank
  placeholder           TODO, FIXME, "description", "n/a", "-", ...
  restates the name     its words are a subset of the name's words plus filler,
                        e.g. entity `lakeshore340` described as
                        "lakeshore340", or parameter `PORT` described as
                        "port".

usage:
    audit-descriptions.py <pattern-dir-or-repo> [...]
    audit-descriptions.py --json report.json /workspaces/ibek-runtime-streamdevice

Needs pyyaml:
    uv run --no-project --with pyyaml python audit-descriptions.py ...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

PLACEHOLDERS = {
    "",
    "-",
    "--",
    ".",
    "todo",
    "tbd",
    "fixme",
    "xxx",
    "n/a",
    "na",
    "none",
    "description",
    "no description",
    "?",
}

# Words that carry no information when they are all that distinguishes a
# description from the name it describes.
FILLER = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
    "and",
    "or",
    "is",
    "this",
    "its",
    "it",
    "value",
    "values",
    "parameter",
    "parameters",
    "param",
    "macro",
    "setting",
    "settings",
}
# Deliberately NOT filler: `object`, `entity`, `model`, `record`. They are ibek
# and EPICS domain terms, so "Object name" for a parameter called `name` reads
# as the house idiom rather than as a restatement. Add them to FILLER to run the
# audit strictly.

SPLIT = re.compile(r"[^A-Za-z0-9]+")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def words(text: str) -> set[str]:
    out: set[str] = set()
    for chunk in SPLIT.split(text or ""):
        for part in CAMEL.split(chunk):
            if part:
                out.add(part.lower())
    return out


def classify(name: str, description) -> str | None:
    """Return a flag reason, or None when the description is acceptable."""
    if description is None:
        return "missing"
    if not isinstance(description, str):
        return f"not a string ({type(description).__name__})"
    text = description.strip()
    if text.lower() in PLACEHOLDERS:
        return "placeholder" if text else "empty"
    if len(text) < 4:
        return f"too short ({text!r})"
    informative = words(text) - FILLER - words(name)
    if not informative:
        return f"restates the name ({text!r} vs {name!r})"
    return None


def audit_file(path: Path) -> list[dict]:
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [{"file": str(path), "where": "<file>", "reason": f"unparseable: {exc}"}]
    findings: list[dict] = []
    module = doc.get("module", path.stem)
    for model in doc.get("entity_models") or []:
        if not isinstance(model, dict):
            continue
        mname = model.get("name", "<unnamed>")
        reason = classify(mname, model.get("description"))
        if reason:
            findings.append(
                {
                    "file": str(path),
                    "module": module,
                    "where": f"entity_model {mname}",
                    "reason": reason,
                }
            )
        params = model.get("parameters") or {}
        if isinstance(params, dict):
            items = params.items()
        else:  # a list of {name: ..., description: ...}
            items = [
                (p.get("name", "<unnamed>"), p) for p in params if isinstance(p, dict)
            ]
        for pname, pdef in items:
            if not isinstance(pdef, dict):
                continue
            reason = classify(str(pname), pdef.get("description"))
            if reason:
                findings.append(
                    {
                        "file": str(path),
                        "module": module,
                        "where": f"entity_model {mname} / parameter {pname}",
                        "reason": reason,
                    }
                )
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, help="write full findings here")
    args = ap.parse_args()

    files: list[Path] = []
    for root in args.roots:
        if root.is_file():
            files.append(root)
        else:
            files += sorted(root.rglob("*.ibek.support.yaml"))

    findings: list[dict] = []
    for f in files:
        findings += audit_file(f)

    by_pattern: dict[str, int] = {}
    for f in findings:
        key = Path(f["file"]).parent.name
        by_pattern[key] = by_pattern.get(key, 0) + 1

    for f in findings:
        print(f"{Path(f['file']).parent.name}\t{f['where']}\t{f['reason']}")
    print(
        f"\n{len(findings)} flagged description(s) across "
        f"{len(by_pattern)} of {len(files)} support yaml file(s)",
        file=sys.stderr,
    )
    if args.json:
        args.json.write_text(json.dumps(findings, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
