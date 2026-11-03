#!/usr/bin/env python3
"""Build a small made-up site to try the tool on: one support repo, with its one module
committed, one release tree with a database and an EDM screen, one settings file.

Usage: make_example.py <empty or new folder>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SUPPORT_YAML = """\
module: demoHeater

entity_models:
  - name: controller
    description: A made-up heater controller
    parameters:
      P:
        type: str
        description: PV prefix
    databases:
      - file: $(DEMOHEATER)/db/demoHeater.template
        args:
          P:
"""

INSTALL_YML = """\
module: demoHeater
version: 1-0
"""

TEMPLATE = """\
record(ai, "$(P):TEMP") {
    field(DESC, "Temperature")
}
record(ao, "$(P):SP") {
    field(DESC, "Set point")
}
record(bo, "$(P):MODE") {
    field(DESC, "Mode")
    field(ZNAM, "Manual")
    field(ONAM, "Auto")
}
record(bo, "$(P):ENABLE") {
    field(DESC, "Heater enable")
    field(ZNAM, "Off")
    field(ONAM, "On")
}
record(ao, "$(P):RATE") {
    field(DESC, "Ramp rate")
}
"""


def obj(cls: str, x: int, y: int, w: int, h: int, **props) -> str:
    lines = [f"object {cls}", "beginObjectProperties", f"x {x}", f"y {y}", f"w {w}", f"h {h}"]
    for k, v in props.items():
        lines.append(k if v is True else f'{k} "{v}"')
    return "\n".join([*lines, "endObjectProperties", ""])


def text(y: int, value: str) -> str:
    lines = ["object activeXTextClass", "beginObjectProperties", "x 10", f"y {y}", "w 100", "h 20", 'value {', f'  "{value}"', "}"]
    return "\n".join([*lines, "endObjectProperties", ""])


def screen() -> str:
    gate = {"visPv": "$(P):MODE", "visMin": "1", "visMax": "2"}
    parts = [
        "4 0 1\nbeginScreenProperties\nmajor 4\nw 400\nh 200\nendScreenProperties\n",
        text(10, "Temperature"),
        obj("TextupdateClass", 120, 10, 100, 20, controlPv="$(P):TEMP"),
        text(40, "Set Point"),
        obj("TextentryClass", 120, 40, 100, 20, controlPv="$(P):SP"),
        text(70, "Mode"),
        obj("activeMenuButtonClass", 120, 70, 100, 20, controlPv="$(P):MODE"),
        # drawn only in Auto, so gated: `Heater Enable` and `Rate` are what classify judges
        text(100, "Heater Enable"),
        obj("activeMenuButtonClass", 120, 100, 100, 20, controlPv="$(P):ENABLE", **gate),
        text(130, "Ramp Rate"),
        obj("TextentryClass", 120, 130, 100, 20, controlPv="$(P):RATE", **gate),
    ]
    return "\n".join(parts)


DBD_COMMON = "field(DESC,DBF_STRING)\nfield(SCAN,DBF_MENU)\nfield(PROC,DBF_UCHAR)\nfield(SEVR,DBF_MENU)\n"

SETTINGS = """\
# Paths are relative to this file. A real site lists its own roots, or takes the defaults.
repos:
  demo: support
prod_roots: [prod/support]
work_roots: []
older_roots: []
last_resort_modules: []
base_dbd: base/dbd
support_dbd_glob: prod/support/*/*/dbd/{}Record.dbd
classification: classification.yaml
classify_rules: classify-rules.yaml
overrides: overrides
"""

RULES = """\
read:
  - module: demoHeater
    pv: ":RATE$"
    class: mode-only
    evidence: ramp rate, only shown in Auto where it applies
    names_only: false
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make(root: Path) -> None:
    support = root / "support" / "demoHeater"
    release = root / "prod" / "support" / "demoHeater" / "1-0"
    dbd = root / "base" / "dbd"
    for d in (support, release / "db", release / "data", dbd, root / "overrides"):
        d.mkdir(parents=True, exist_ok=True)
    (support / "demoHeater.ibek.support.yaml").write_text(SUPPORT_YAML)
    (support / "demoHeater.install.yml").write_text(INSTALL_YML)
    (release / "db" / "demoHeater.template").write_text(TEMPLATE)
    (release / "data" / "demoHeater.edl").write_text(screen())
    (dbd / "dbCommon.dbd").write_text(DBD_COMMON)
    for rtype in ("ai", "ao", "bo"):
        (dbd / f"{rtype}Record.dbd").write_text(f"recordtype({rtype}) {{\n\tfield(VAL,DBF_DOUBLE) {{\n\t}}\n}}\n")
    (root / "pvi-from-edm.yaml").write_text(SETTINGS)
    (root / "classify-rules.yaml").write_text(RULES)
    (root / "classification.yaml").write_text("[]\n")
    repo = root / "support"
    git(repo, "init", "--quiet", "--initial-branch=main")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=example", "-c", "user.email=example@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "A made-up support module")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    make(Path(sys.argv[1]))
    print(sys.argv[1])
