#!/usr/bin/env python3
"""Write the classification file from gated-evidence.json: deterministic rules first, then
what was judged by reading, kept in the rules file. Entries a person has edited (their
`judged` starts `person`) are kept as they are.
"""

from __future__ import annotations

import html
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from protect import UNGATED  # noqa: E402
from settings import CFG  # noqa: E402

# A warning as a sentence: legends such as "High Temp Trip" and headings such as
# "Interlocks" name a state and warn of nothing.
WARNING = re.compile(r"^\s*(warning|caution|danger)\s*!?\s*$|\bwill trip\b|\bcan cause\b|\bmay cause\b|\bdamage\b|\bare you sure\b|\bhazard", re.I)

# Rule name -> pattern over the record name, DESC, on-screen labels and entity.
NAME_RULES = [
    ("name-hv", r"\bHV\b|CCHV|SETHV|CCCON|high.?volt|cold cathode"),
    ("name-interlock", r"interlock|\bILK\b|_ILK_|_IL\d|\bMPS\b"),
    ("name-valve", r"valve|vacValve|\bV\d+(_CMD|_SP)?\b|Eng_?V\d+|(SET|OPEN|CLOSE)_V\d+"),
    ("name-heater", r"heater"),
    ("name-pump", r"pump"),
    ("name-filament", r"filament|FILCON"),
    ("name-multiplier", r"multiplier|MLTCON"),
    ("name-power", r"\bpower\b|\bpwr\b"),
    ("name-reset", r"reset|reboot|restart"),
    ("name-stop", r"\bestop\b|\babort\b|\bstop\b|_STOP\b|:STOP\b|:KILL\b"),
]

# Gates saying which variant of hardware or firmware this is.
CAPABILITY = re.compile(r"EXISTS|HASDEBOUNCE|SYS_VER|CSTYPE|TRANSDUCERTYPE|:HMT$|_SETUP$", re.I)
PASSWORD_GATE = re.compile(r"Pwd\d_OK", re.I)


@lru_cache(maxsize=None)
def site_rules() -> dict:
    """Judged by reading the evidence, so specific to the site's modules. In the rules file:

    read: consulted in order before the mode-only rules, so a reading can stop a control
      from being called mode-only; the first match wins. Each entry has module (a regex on
      the whole name), pv (a regex), class, evidence and names_only.
    read_last: the same, consulted after every other rule that gives a mode-only.
    engineering_gates: {pattern, evidence}, gates that show a control in engineering mode only.
    """
    rules = yaml.safe_load(CFG.classify_rules.read_text()) if CFG.classify_rules else {}
    return {"read": [], "read_last": [], "engineering_gates": [], **(rules or {})}


def read_rule(r: dict, which: str) -> tuple[str, str, str, bool] | None:
    for e in site_rules()[which]:
        if re.fullmatch(e.get("module", ".*"), r["module"]) and re.search(e["pv"], r["pv"]):
            return e["class"], "read", e["evidence"], e["names_only"]
    return None


def rule_for(r: dict) -> tuple[str, str, str, bool]:
    """(class, judged, evidence, names only)."""
    rec = r.get("record", {})
    text = " ".join([r["pv"], rec.get("desc", ""), *r["dialog_text"], " ".join(x.split("=", 1)[-1] for x in r.get("labels", []) if not x.startswith("row=") and not x.startswith("pressValue"))])
    gates = [g for g, _ in r["gates"]]
    gate = gates[0] if gates else ""
    cond = r["gates"][0][1].replace("visible when ", "") if gates else ""
    for src in [*r["dialog_text"], *r.get("screen_warnings", [])]:
        if WARNING.search(src):
            return "dangerous", "rule:warning-text", f"screen warns: {src.strip()[:90]}", False
    for name, g in r.get("gate_records", {}).items():
        if re.search(r"\bwarning\b", g.get("desc", ""), re.I):
            return "dangerous", "rule:warning-text", f"gate `{name}` is `{g['desc']}`", False
    if any(c == "widget asks for a password" for _, c in r["gates"]):
        return "dangerous", "rule:password-widget", "the screen's button asks for a password", False
    if any(PASSWORD_GATE.search(g) for g in gates):
        return "dangerous", "rule:password-gate", "shown only after a password level is entered", False
    for eg in site_rules()["engineering_gates"]:
        if any(re.search(eg["pattern"], g, re.I) for g in gates):
            return "dangerous", "rule:engineering-gate", eg["evidence"], True
    for name, pat in NAME_RULES:
        if m := re.search(pat, f"{text} {r['entity'] if name == 'name-valve' else ''}", re.I):
            return "dangerous", f"rule:{name}", f"name says `{m.group(0)}`; desc `{rec.get('desc', '')}`", True
    if hit := read_rule(r, "read"):
        return hit
    if gates and all(g.endswith(".DISA") and g.startswith(r["pv"] + ".") for g in gates):
        return "mode-only", "rule:own-disa", "gate is the record's own DISA: hidden while the record is disabled", False
    if gates and all(CAPABILITY.search(g) for g in gates):
        return "mode-only", "rule:capability-gate", f"gate `{gate}` says which hardware or firmware this is ({cond})", False
    states = [v for g in r.get("gate_records", {}).values() for v in g.get("states", []) if v]
    if gates and len(gates) == len(set(gates)) and len(states) >= 2 and all(v.get("states") for v in r.get("gate_records", {}).values()):
        return "mode-only", "rule:selector-gate", f"gate `{gate}` selects among {'/'.join(states[:4])}; hides what doesn't apply", False
    if hit := read_rule(r, "read_last"):
        return hit
    return "unsure", "rule:no-rule", f"gate `{gate}` ({cond}), desc `{rec.get('desc', '')}`: no evidence either way", True


def sort_key(e: dict) -> tuple:
    rank = 0 if e["class"] == "dangerous" and e["names_only"] else 1 if e["class"] == "unsure" else 2 if e["class"] == "dangerous" else 3
    return (rank, e["module"], e["entity"], e["pv"])


HEADER = """\
# Gated writes in generated PVI, classified. gen.py reads this on every run:
#   dangerous, unsure: moved into the device's `Protected Controls` sub-screen
#   mode-only: left where it is
#   keep-on-main: left where it is by owner decision, whatever the rules would say
#   momentary: EDM writes one value on press and another on release; two actions in one
#     panel, in `Protected Controls`, gated or not and even from behind a dialog (owner decision).
#     On `.PROC` only the press action: a write to `.PROC` processes the record whatever the
#     value, so a release action would repeat the press rather than undo it. A `.PROC`
#     button of class keep-on-main follows the same rule.
# Change `class` and regenerate; set `judged: person` so classify.py keeps your edit.
# A gated write missing from this file counts as unsure.
# not_placed: why a momentary PV has no widget at all.
# behind_dialog: already behind a confirmation dialog, which stays; classified only.
# names_only: judged from names and labels alone, nothing on the screen says so.
# password_gated: the EDM screen asks for a password first; PVI has no such gate.
# Sorted most doubtful first: dangerous from names only, unsure, then the rest.
"""


def password_gated(r: dict) -> bool:
    return any(PASSWORD_GATE.search(g) or c == "widget asks for a password" for g, c in r["gates"])


def build(rows: list[dict], previous: dict) -> list[dict]:
    out = []
    for r in rows:
        key = (r["module"], r["entity"], r["pv"])
        if (old := previous.get(key)) and str(old.get("judged", "")).startswith("person"):
            e = old
        else:
            cls, judged, evidence, names = rule_for(r)
            e = dict(module=r["module"], entity=r["entity"], pv=r["pv"], **{"class": cls}, evidence=evidence, judged=judged,
                     names_only=names, behind_dialog=r["behind_dialog"])
        e.pop("password_gated", None)
        if password_gated(r):
            e["password_gated"] = True
        out.append(e)
    # these need not be gated, so the evidence may not list them
    listed = {(e["module"], e["entity"], e["pv"]) for e in out}
    out += [e for k, e in previous.items() if e["class"] in UNGATED and k not in listed]
    out.sort(key=sort_key)
    return out


def write_review():
    """The review list, grouped by module, the most doubtful module first."""
    entries = yaml.safe_load(CFG.classification.read_text()) or [] if CFG.classification else []
    moved = {}
    for f in CFG.output.glob("*/report.json"):
        rep = json.loads(f.read_text())
        for d in rep["devices"].values():
            for pv in d.get("protected", {}):
                moved[(f.parent.name, d["entity"], pv)] = True
    modules: dict[str, list[dict]] = {}
    for e in entries:
        modules.setdefault(e["module"], []).append(e)

    def doubt(m: str) -> tuple:
        rows = modules[m]
        return (-sum(1 for e in rows if e["class"] == "dangerous" and e.get("names_only")), -sum(1 for e in rows if e["class"] == "unsure"), m)

    counts = {c: sum(1 for e in entries if e["class"] == c) for c in ("dangerous", "unsure", "mode-only", "keep-on-main", "momentary")}
    parts = [f"<h1>Gated writes, classified</h1><p class=note>{len(entries)} writes in {len(modules)} modules: {counts['dangerous']} dangerous, {counts['unsure']} unsure, "
             f"{counts['mode-only']} mode-only, {counts['momentary']} momentary, {counts['keep-on-main']} kept on the main screen by owner decision, {sum(1 for e in entries if e.get('password_gated'))} password-gated on EDM. Judged from names and screen text, with no IOC running. To change one, edit the classification file and regenerate.</p>"]
    for m in sorted(modules, key=doubt):
        rows = modules[m]
        cc = {c: sum(1 for e in rows if e["class"] == c) for c in counts}
        n_moved = sum(1 for e in rows if (e["module"], e["entity"], e["pv"]) in moved)
        trs = []
        for e in rows:
            key = (e["module"], e["entity"], e["pv"])
            where = "behind its dialog" if e.get("behind_dialog") else "Protected Controls" if key in moved else "main screen"
            cells = [e["class"] + (" (names only)" if e.get("names_only") else "") + (" (password on EDM)" if e.get("password_gated") else ""), where, e["pv"], e["entity"], e["evidence"], e["judged"]]
            trs.append(f'<tr class="{html.escape(e["class"])}">' + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>")
        parts.append(f'<details id="{html.escape(m)}" open><summary><b>{html.escape(m)}</b>: {cc["dangerous"]} dangerous, {cc["unsure"]} unsure, {cc["mode-only"]} mode-only; {n_moved} moved '
                     f'(<a href="{html.escape(m)}.html">module page</a>)</summary><div class=wrap><table><tr><th>class</th><th>where</th><th>PV</th><th>entity</th><th>evidence</th><th>judged</th></tr>{"".join(trs)}</table></div></details>')
    css = """:root{color-scheme:light dark;--bg:#fff;--fg:#1c2327;--mute:#5d6b73;--line:#d5dcdf;--d:#fbe9e7;--u:#fff6dc;--m:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#14191c;--fg:#e4e9eb;--mute:#9aa8af;--line:#334048;--d:#3a2220;--u:#37301a;--m:#14191c}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}
.note{color:var(--mute)}details{margin:10px 0}summary{cursor:pointer;padding:4px 0}.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}
td,th{border:1px solid var(--line);padding:3px 7px;text-align:left;vertical-align:top}td:nth-child(3){font-family:ui-monospace,monospace;font-size:12px;white-space:nowrap}
tr.dangerous td:first-child{background:var(--d)}tr.unsure td:first-child{background:var(--u)}a{color:inherit}"""
    CFG.review.mkdir(parents=True, exist_ok=True)
    (CFG.review / "gated-review.html").write_text(f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Gated writes review</title><style>{css}</style></head><body>{"".join(parts)}</body></html>')


def main(out: Path | None = None):
    """Write the classification file, or `out` to leave it as it is."""
    rows = json.loads((CFG.status / "gated-evidence.json").read_text())
    previous = {}
    if CFG.classification and CFG.classification.exists():
        previous = {(e["module"], e["entity"], e["pv"]): e for e in yaml.safe_load(CFG.classification.read_text()) or []}
    entries = build(rows, previous)
    out = out or CFG.classification
    if out is None:
        raise SystemExit("classify: no classification file to write: give --classification or --out")
    out.write_text(HEADER + yaml.safe_dump(entries, sort_keys=False, width=200, allow_unicode=True))
    print(len(entries))
