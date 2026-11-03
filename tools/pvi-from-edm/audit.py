#!/usr/bin/env python3
"""Independent checks on a finished sweep, from the EDM screens and the .bob files
rather than from what the generator says it did. Writes audit.json; exit 1 on a failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from edl import expand, parse_edl, pv_uses  # noqa: E402
from gen import field_pv, is_panel, resolve, screen_extent, walk_signals  # noqa: E402
from protect import MOVED, SUB_LABEL  # noqa: E402
from settings import CFG  # noqa: E402

WRITE_BOB = {"textentry", "combo", "slide_button"}
PROTECTED_BOB = "_" + SUB_LABEL.replace(" ", "")


class Lookup:
    """What gen.resolve needs of a build context."""

    def __init__(self, records):
        self.records = records
        self.sweep = True
        self.notes: list[str] = []


def bob_writes(path: Path) -> dict[str, list[tuple[str, str]]]:
    """PV to (text, value) of what a .bob can write; widgets that aren't buttons have no value."""
    out: dict[str, list[tuple[str, str]]] = {}
    for w in ET.parse(path).getroot().iter("widget"):
        t = w.get("type")
        if t == "action_button":
            for a in w.iter("action"):
                if a.get("type") == "write_pv":
                    out.setdefault(a.findtext("pv_name") or "", []).append((w.findtext("text") or "", a.findtext("value") or ""))
        elif t in WRITE_BOB:
            out.setdefault(w.findtext("pv_name") or "", []).append((t, ""))
    return out


def audit_buttons(key: str, stem: str, d: dict, folder: Path) -> dict:
    """Every message button on every screen the device was built from, against its file."""
    tree = yaml.safe_load((folder / f"{d['file_stem']}.pvi.device.yaml").read_text())["children"]
    panels: dict[str, set] = {}
    others: dict[str, str] = {}
    for c in walk_signals(tree):
        if is_panel(c):
            panels.setdefault(c["write_pv"], set()).update(c["write_widget"]["actions"].values())
        elif "write_pv" in c:
            others[c["write_pv"]] = c["write_widget"]["type"]
    records = dict.fromkeys(list(d["placed"]) + [r[0] for r in d["left_out"]], True)
    res: dict = dict(checked=0, in_panel=0, reasons={}, missing=[], momentary=[])
    seen = set()
    for s in d["screens"]:
        scr = parse_edl(Path(s["path"]))
        W, H = screen_extent(scr)
        for o in scr.objects:
            if o.cls != "activeMessageButtonClass":
                continue
            for u in pv_uses(o):
                if u.role != "write":
                    continue
                res["checked"] += 1
                pv = expand(u.pv, s["env"])
                rec, fld = resolve(Lookup(records), pv)
                value = o.get("pressValue") or o.get("releaseValue")
                value = str(value) if value is not None else "1"
                full = field_pv(rec, fld) if rec else pv
                off = o.get("releaseValue")
                if off is not None and str(off) != value:
                    if o.get("toggle"):
                        if str(off) not in panels.get(full, ()):
                            res["missing"].append(dict(module=key, device=stem, pv=full, value=str(off), screen=s["file"]))
                    else:
                        res["momentary"].append([key, stem, full, value, str(off)])
                why = None
                if o.x >= W or o.y >= H:
                    why = "drawn outside the window"
                elif rec is None:
                    why = "record not in the database"
                elif full in d["fields_left"] or pv in d["fields_left"]:
                    why = "field left out: " + d["fields_left"].get(full, d["fields_left"].get(pv, ""))
                elif value in panels.get(full, ()):
                    res["in_panel"] += 1
                    continue
                elif full in others:
                    why = f"writable through its {others[full]}"
                if why:
                    res["reasons"][why.split(":")[0]] = res["reasons"].get(why.split(":")[0], 0) + 1
                    seen.add((full, value, why))
                else:
                    res["missing"].append(dict(module=key, device=stem, pv=full, value=value, screen=s["file"]))
    res["left_out"] = sorted(([a, b, c] for a, b, c in seen))
    return res


def audit_momentary(found: list, classes: list[dict], devices: dict) -> dict:
    """Every button the screens write on press and on release, against the class file and
    the .bob files: both values in one panel on Protected, and writable nowhere else. On
    .PROC only the press: any write processes the record, so a release repeats it. A stop
    of class keep-on-main is on the first screen and not on Protected."""
    listed = {(e["module"], e["pv"]): e for e in classes if e["class"] in ("momentary", "keep-on-main")}
    want: dict[tuple, dict] = {}
    for key, stem, pv, press, off in found:
        v = want.setdefault((key, pv), dict(module=key, device=stem, pv=pv, values=set()))
        v["values"] |= {press} if pv.endswith(".PROC") else {press, off}
    rows, bad = [], []
    for k, v in sorted(want.items()):
        e = listed.get(k)
        row = dict(module=v["module"], device=v["device"], pv=v["pv"], values=sorted(v["values"]))
        rows.append(row)
        if e is None:
            bad.append((*k, "not in the classification file as momentary"))
            continue
        if e.get("not_placed"):
            row["not_placed"] = e["not_placed"]
        d = devices.get((e["module"], e["entity"]))
        folder = CFG.sandbox / v["module"] / "opi"
        stem = d[1]["file_stem"] if d else v["device"]
        where = {b.name: bob_writes(b)[v["pv"]] for b in folder.glob(f"{stem}*.pvi.bob") if b.name.startswith((f"{stem}.", f"{stem}_")) and v["pv"] in bob_writes(b)}
        row["actions"] = sorted({a for w in where.values() for a in w})
        prot = [w for n, w in where.items() if PROTECTED_BOB in n]
        rest = [n for n in where if PROTECTED_BOB not in n]
        if e.get("not_placed"):
            if where:
                bad.append((*k, "marked not_placed but drawn"))
            continue
        if v["pv"].endswith(".PROC") and any(t.endswith("Release") for w in where.values() for t, _ in w):
            bad.append((*k, f"a release action on .PROC: {row['actions']}"))
        if e["class"] == "keep-on-main":
            if f"{stem}.pvi.bob" not in where or prot:
                bad.append((*k, f"a stop off the first screen or on Protected: {sorted(where)}"))
            if not v["values"] <= {val for w in where.values() for _, val in w}:
                bad.append((*k, f"writes {row['actions']}, the screen {sorted(v['values'])}"))
            continue
        shown = {val for w in prot for _, val in w}
        if not v["values"] <= shown:
            bad.append((*k, f"on Protected writes {sorted(shown)}, the screen {sorted(v['values'])}"))
        if rest:
            bad.append((*k, f"also writable on {rest}"))
    return dict(rows=rows, bad=bad)


def clean(v: dict) -> bool:
    """A validated entity whose counts say what a pass has to mean. An entity with `pv: true`,
    which only a hand-written section has, emits its PVI records by design."""
    stars = v.get("pv_true") or (v.get("n_record_star_in_files") == 0 and v.get("n_record_star_under_msi") == 0)
    return bool(v.get("generate_matches_generate2")) and stars and not v.get("pvi_pv_missing_from_db") and not v.get("pvi_pv_unexpanded") and not v.get("field_pv_invalid") and v.get("expander") == "msi"


def main() -> int:
    status = json.loads((CFG.status / "sweep-status.json").read_text())
    classes = (yaml.safe_load(CFG.classification.read_text()) or []) if CFG.classification else []
    out: dict = dict(buttons=dict(checked=0, in_panel=0, reasons={}, missing=[], left_out=[], momentary=[]), merged={}, protected=dict(checked=0, on_protected=0, writable_elsewhere=[], not_on_protected=[]), keep_on_main=[], not_ok=[])
    devices = {}
    not_validated = []
    absent: set[str] = set()
    for key, st in status.items():
        if st.get("status") == "hand_written":
            vf = CFG.output / key / "validate.json"
            if not vf.exists():
                not_validated.append(key)
                continue
            val = json.loads(vf.read_text())
            sup = yaml.safe_load((CFG.repos[st["repo"]] / st["dir"] / st["yaml"]).read_text())
            for em in sup.get("entity_models") or []:
                if em.get("pvi"):
                    devices[(st["dir"], em["name"])] = (key, dict(file_stem=em["pvi"]["yaml_path"].split(".")[0]))
            for name, v in val["entities"].items():
                if not v.get("ok") or not clean(v):
                    out["not_ok"].append((key, name, v.get("reason") or v.get("expander")))
            absent.update({t for v in val["entities"].values() for t in v.get("missing_templates") or []})
            continue
        if st.get("status") != "done":
            continue
        rep = json.loads((CFG.output / key / "report.json").read_text())
        val = json.loads((CFG.output / key / "validate.json").read_text())
        for name, v in val["entities"].items():
            if v.get("ok") and not clean(v):
                out["not_ok"].append((key, name, v.get("expander")))
        for stem, d in rep["devices"].items():
            if "error" in d or not (CFG.output / key / f"{d.get('file_stem')}.pvi.device.yaml").exists():
                continue
            devices[(st["dir"], d["entity"])] = (key, d)
            r = audit_buttons(key, stem, d, CFG.output / key)
            b = out["buttons"]
            b["checked"] += r["checked"]
            b["in_panel"] += r["in_panel"]
            b["missing"] += r["missing"]
            b["momentary"] += [m for m in r["momentary"] if m not in b["momentary"]]
            b["left_out"] += [[key, stem, *x] for x in r["left_out"]]
            for k, v in r["reasons"].items():
                b["reasons"][k] = b["reasons"].get(k, 0) + v
            for pv, acts in d.get("merged_buttons", {}).items():
                out["merged"].setdefault(key, {})[pv] = acts
    for e in classes:
        dev = devices.get((e["module"], e["entity"]))
        if dev is None:
            continue
        key, d = dev
        stem = d["file_stem"]
        bobs = {b.name: bob_writes(b) for b in (CFG.sandbox / key / "opi").glob(f"{stem}*.pvi.bob") if b.name.startswith((f"{stem}.", f"{stem}_"))}
        where = sorted(n for n, w in bobs.items() if e["pv"] in w)
        prot = [n for n in where if PROTECTED_BOB in n]
        rest = [n for n in where if PROTECTED_BOB not in n]
        if e["class"] in MOVED and not e.get("behind_dialog"):
            out["protected"]["checked"] += 1
            if prot:
                out["protected"]["on_protected"] += 1
            if rest:
                out["protected"]["writable_elsewhere"].append((key, e["pv"], rest))
            if not prot and not rest:
                out["protected"]["not_on_protected"].append((key, e["pv"]))
        if e["class"] in MOVED and e.get("behind_dialog") and f"{stem}.pvi.bob" in where:
            out["protected"].setdefault("dialog_entry_on_first_screen", []).append((key, e["pv"]))
        if e["class"] == "keep-on-main":
            out["keep_on_main"].append(dict(module=key, pv=e["pv"], bobs=where, on_root=f"{stem}.pvi.bob" in where, protected=bool(prot)))
    out["momentary"] = audit_momentary(out["buttons"]["momentary"], classes, devices)
    out["merged_count"] = sum(len(v) for v in out["merged"].values())
    out["merged_not_in_bob"] = []
    for key, pvs in out["merged"].items():
        all_bobs: dict = {}
        for b in (CFG.sandbox / key / "opi").glob("*.pvi.bob"):
            for pv, w in bob_writes(b).items():
                all_bobs.setdefault(pv, []).extend(w)
        for pv, acts in pvs.items():
            shown = {v for _, v in all_bobs.get(pv, [])}
            if not set(acts.values()) <= shown:
                out["merged_not_in_bob"].append((key, pv, sorted(shown)))
    out["merged_by_module"] = {k: len(v) for k, v in sorted(out["merged"].items())}
    out["password_gated"] = sum(1 for e in classes if e.get("password_gated"))
    (CFG.status / "audit.json").write_text(json.dumps(out, indent=1, default=str))
    b = out["buttons"]
    print(f"buttons: {b['checked']} on screens, {b['in_panel']} in a panel, left out with a reason {b['reasons']}, missing {len(b['missing'])}; {len(b['momentary'])} momentary uses")
    print(f"merged: {out['merged_count']} {out['merged_by_module']}; a value absent from the .bob: {len(out['merged_not_in_bob'])}")
    print(f"momentary distinct PVs: {len(out['momentary']['rows'])}, of them not placed: {sum(1 for r in out['momentary']['rows'] if r.get('not_placed'))}; wrong: {out['momentary']['bad']}")
    p = out["protected"]
    print(f"protected: {p['checked']} checked, {p['on_protected']} on Protected, writable elsewhere {len(p['writable_elsewhere'])}, placed nowhere {len(p['not_on_protected'])}")
    for k in out["keep_on_main"]:
        print(f"  keep-on-main {k['module']} {k['pv']}: root={k['on_root']} protected={k['protected']} {k['bobs']}")
    print(f"password gated: {out['password_gated']}; entities not clean: {len(out['not_ok'])}")
    print(f"written by hand: not validated {sorted(not_validated)}; templates an entity loads and upstream lacks {sorted(absent)}")
    print(f"behind-dialog entries on a first screen: {p.get('dialog_entry_on_first_screen', [])}")
    return 1 if out["momentary"]["bad"] or b["missing"] or out["merged_not_in_bob"] or p["writable_elsewhere"] or out["not_ok"] or not all(k["on_root"] and not k["protected"] for k in out["keep_on_main"]) else 0
