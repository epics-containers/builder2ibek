#!/usr/bin/env python3
"""Gather what is known about each gated write in the generated PVI: the record
and its gate from the db, the widget and warning text from the screens. Facts only;
classify.py draws the conclusions."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from dbparse import default_of, parse_db  # noqa: E402
from edl import expand, gate_conditions, parse_edl, pv_uses, text_of  # noqa: E402
from release import db_search_path, find_db  # noqa: E402
from settings import CFG  # noqa: E402

WARN = re.compile(r"\b(warn\w*|caution|danger\w*|trip\w*|damage\w*|are you sure|interlock\w*|hazard\w*|do not|don't|never|expert|engineer\w*|protect\w*)\b", re.I)
STATE_FIELDS = ["ZNAM", "ONAM", "ZRST", "ONST", "TWST", "THST", "FRST", "FVST", "SXST", "SVST"]


def rec_facts(rec) -> dict:
    if rec is None:
        return {}
    f = rec.fields
    out = dict(type=rec.rtype, desc=default_of(f.get("DESC", "")))
    states = [default_of(f[k]) for k in STATE_FIELDS if k in f]
    if states:
        out["states"] = states
    for k in ("OUT", "INP", "EGU"):
        if k in f:
            out[k] = f[k][:60]
    return out


def gate_records(gate: str) -> list[str]:
    """Records named by a gate: a plain PV, or the arguments of an EDM CALC."""
    m = re.search(r"\}\((.*?)\)*$", gate)
    names = m.group(1).split(",") if m else [gate]
    return [n.strip().partition(".")[0] for n in names if n.strip()]


def tail_eq(screen_pv: str, pv: str) -> bool:
    return screen_pv == pv or screen_pv == pv + ".VAL"


def gather() -> list[dict]:
    gated = json.loads((CFG.status / "gated-writes.json").read_text())
    rows: dict[tuple, dict] = {}
    for g in gated:
        if g["kind"] == "visibility_gated_write" and not g["handled"].startswith(("included", "moved")):
            continue
        if g["kind"] == "small_dialog_inlined":
            continue
        pvs = [p.strip() for p in g["pv"].split(",") if p.strip()]
        for pv in pvs:
            k = (g["module"], g["entity"], pv)
            r = rows.setdefault(k, dict(module=g["module"], repo=g["repo"], entity=g["entity"], pv=pv, gates=[], screens=[], dialog_text=[], behind_dialog=False))
            if g["screen"] not in r["screens"]:
                r["screens"].append(g["screen"])
            if g["kind"] == "visibility_gated_write":
                if [g["gate_pv"], g["condition"]] not in r["gates"]:
                    r["gates"].append([g["gate_pv"], g["condition"]])
                if "behind" in g["handled"]:
                    r["behind_dialog"] = True
                if g.get("via_link"):
                    r["via_link"] = True
            else:
                r["behind_dialog"] = True
                r["dialog_text"].append(g["text"])
    byrep = defaultdict(list)
    for r in rows.values():
        if r.get("via_link"):
            r["behind_dialog"] = False  # it moves from behind its dialog
        byrep[r["module"]].append(r)
    for mod, rs in byrep.items():
        rep = json.loads((CFG.output / mod / "report.json").read_text())
        release = Path(rep["release"])
        extra = [CFG.repos[rep["repo"]] / rep["folder"]]
        sup = yaml.safe_load((CFG.output / mod / rep["yaml"]).read_text())
        ems = {e["name"]: e for e in sup.get("entity_models") or []}
        for r in rs:
            dev = next((d for d in rep["devices"].values() if d.get("entity") == r["entity"]), None)
            if dev is None:
                r["no_device"] = True
                continue
            records = {}
            for d in ems[r["entity"]].get("databases") or []:
                f = d.get("file", "").strip()
                if not f or "{{" in f:
                    continue
                p = find_db(release, f, extra)
                if p:
                    records.update(parse_db(p, search=db_search_path(release, extra)).records)
            r["record"] = rec_facts(records.get(r["pv"].partition(".")[0]))
            r["gate_records"] = {n: rec_facts(records.get(n)) for g, _ in r["gates"] for n in gate_records(g)}
            words = set()
            labels = set()
            for s in dev["screens"]:
                if s["file"] not in r["screens"]:
                    continue
                obj = parse_edl(Path(s["path"]))
                env = s["env"]
                texts = [o for o in obj.objects if o.cls == "activeXTextClass" and text_of(o)]
                for t in texts:
                    if WARN.search(text_of(t)):
                        words.add(text_of(t).strip()[:120])
                for o in obj.objects:
                    if not any(u.role == "write" and tail_eq(expand(u.pv, env), r["pv"]) for u in pv_uses(o)):
                        continue
                    for k in ("onLabel", "offLabel", "label", "pressValue"):
                        if o.get(k):
                            labels.add(f"{k}={o.get(k)}"[:50])
                    for t in texts:
                        if abs(t.cy - o.cy) <= max(o.h, 12) and t.x2 <= o.x + 6 and o.x - t.x2 < 220:
                            labels.add("row=" + text_of(t).strip()[:60])
            r["screen_warnings"] = sorted(words)
            r["labels"] = sorted(labels)
    return list(rows.values())


def main():
    rows = gather()
    (CFG.status / "gated-evidence.json").write_text(json.dumps(rows, indent=1))
    print(len(rows))
