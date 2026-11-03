#!/usr/bin/env python3
"""Self-contained review pages: EDM screen from real coordinates, beside the
generated PVI as laid out in the .bob from its coordinates.
"""

from __future__ import annotations

import html
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from dbparse import static_suffix  # noqa: E402
from edl import expand, links, parse_edl, pv_uses, text_of  # noqa: E402
from settings import CFG  # noqa: E402

MAX_SCREENS = 12
PALETTE = ["#d7263d", "#1b6ca8", "#2a9d3f", "#c77800", "#7b2cbf", "#008b8b", "#c2185b", "#5d6d1e", "#37474f", "#6d4c41"]


@lru_cache(maxsize=None)
def edm_colors() -> dict[int, str]:
    out = {}
    if CFG.edm_colors is None or not CFG.edm_colors.exists():
        return out
    idx = 0
    for ln in CFG.edm_colors.read_text(errors="replace").splitlines():
        m = re.match(r'\s*static\s+(\d+)\s+"[^"]*"\s*\{\s*(\d+)\s+(\d+)\s+(\d+)', ln)
        if m:
            idx = int(m.group(1))
            r, g, b = (int(m.group(i)) // 257 for i in (2, 3, 4))
            out[idx] = f"#{r:02x}{g:02x}{b:02x}"
    return out




def col(o, key, default):
    v = o.get(key)
    if isinstance(v, str) and (m := re.match(r"index (\d+)", v)):
        return edm_colors().get(int(m.group(1)), default)
    return default


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def group_map(device: dict) -> tuple[dict, list[str]]:
    """PV -> top-level group title in the device, and the group order."""
    pvs: dict[str, str] = {}
    order: list[str] = []

    def walk(tree, top, path):
        for c in tree:
            if c["type"] == "Group" and c["layout"]["type"] in ("Grid", "SubScreen"):
                t = c.get("label") or c["name"]
                full = path + [t]
                if len(full) == 1 or c["layout"]["type"] == "Grid":
                    name = " / ".join(full)
                    if name not in order:
                        order.append(name)
                walk(c["children"], name if (len(full) == 1 or c["layout"]["type"] == "Grid") else top, full)
            elif c["type"] == "Group":
                walk(c["children"], top, path)
            elif c["type"].startswith("Signal"):
                for k in ("read_pv", "write_pv"):
                    if k in c:
                        pvs[c[k]] = top or "(top level)"
    walk(device["children"], None, [])
    return pvs, order


def color_for(name: str, order: list[str]) -> str:
    return PALETTE[order.index(name) % len(PALETTE)] if name in order else "#888"


def resolve(pv: str, pvs: dict) -> str | None:
    base = pv.partition(".")[0]
    if base in pvs:
        return base
    suf = static_suffix(base)
    hits = [p for p in pvs if static_suffix(p) == suf]
    return hits[0] if len(hits) == 1 else None


def draw_edl(path: str, env: dict, pvs: dict, order: list[str], db_records: set) -> str:
    s = parse_edl(Path(path))
    W = max([s.w] + [o.x2 for o in s.objects if o.x2 < 1000] + [0])
    H = max([s.h] + [o.y2 for o in s.objects] + [0])
    bg = edm_colors().get(s.bg, "#bbb") if s.bg is not None else "#bbb"
    out = [f'<div class="scr" style="width:{W}px;height:{H}px;background:{bg}">']
    if s.h and s.h < H:
        out.append(f'<div class="fold" style="top:{s.h}px;width:{W}px"></div>')
    if s.w and s.w < W:
        out.append(f'<div class="foldv" style="left:{s.w}px;height:{H}px"></div>')
    z = 0
    # shapes first, largest at the back, as EDM draws frames behind widgets
    def key(o):
        shape = o.cls in ("activeRectangleClass", "activeCircleClass", "activeLineClass")
        return (0 if shape else 1, -(o.w * o.h))

    for o in sorted(s.objects, key=key):
        z += 1
        st = f"left:{o.x}px;top:{o.y}px;width:{o.w}px;height:{o.h}px;z-index:{z};"
        if o.cls == "activeRectangleClass":
            fill = col(o, "fillColor", "transparent") if o.get("fill") else "transparent"
            line = col(o, "lineColor", "#000")
            out.append(f'<div class="o" style="{st}background:{fill};border:1px solid {line}"></div>')
        elif o.cls == "activeCircleClass":
            fill = col(o, "fillColor", "transparent") if o.get("fill") else "transparent"
            out.append(f'<div class="o" style="{st}background:{fill};border:1px solid #444;border-radius:50%"></div>')
        elif o.cls == "activeXTextClass":
            t = expand(text_of(o), env)
            fg = col(o, "fgColor", "#000")
            bgc = "transparent" if o.get("useDisplayBg") else col(o, "bgColor", "transparent")
            al = o.get("fontAlign", "left")
            out.append(f'<div class="o t" title="{esc(t)}" style="{st}color:{fg};background:{bgc};text-align:{al}">{esc(t)}</div>')
        elif o.cls in ("activeExitButtonClass", "shellCmdClass"):
            lab = o.get("label") or o.get("buttonLabel") or "cmd"
            out.append(f'<div class="o chrome" title="not converted" style="{st}">{esc(lab)}</div>')
        elif o.cls in ("relatedDisplayClass", "activePipClass"):
            lks = links(o)
            lab = (o.get("buttonLabel") or (lks[0]["label"] if lks else "") or (lks[0]["file"] if lks else ""))
            tgt = ", ".join(f"{ln['file']} {ln['symbols']}" for ln in lks)
            kind = "lk" if o.cls == "relatedDisplayClass" else "pip"
            out.append(f'<div class="o {kind}" title="{esc(tgt)}" style="{st}">{esc(lab)}</div>')
        else:
            uses = [u for u in pv_uses(o) if u.role != "decor"]
            if not uses:
                continue
            u = uses[0]
            pv = expand(u.pv, env)
            rec = resolve(pv, pvs)
            role = u.role
            if rec:
                c = color_for(pvs[rec], order)
                cls = "w" if role == "write" else "r"
                extra = f"border-color:{c};background:{c}22"
            else:
                cls = "x"
                extra = ""
            tip = f"{pv} [{o.cls.replace('Class', '')}]" + ("" if rec else " NOT IN PVI")
            short = static_suffix(pv.split(".")[0]).lstrip(":-_")
            if "$(" in short:
                short = short[short.rindex(")") + 1 :].lstrip(":-_")
            dot = ("." + pv.partition(".")[2]) if "." in pv else ""
            out.append(f'<div class="o pv {cls}" data-pv="{esc(rec or pv)}" title="{esc(tip)}" style="{st}{extra}">{esc(short + dot)}</div>')
    out.append("</div>")
    return "".join(out)


def draw_bob(path: Path, pvs: dict, order: list[str]) -> str:
    root = ET.parse(path).getroot()
    W, H = int(root.findtext("width")), int(root.findtext("height"))
    out = [f'<div class="scr bob" style="width:{W}px;height:{H}px">']

    def walk(node, ox, oy, group_title):
        for w in node.findall("widget"):
            t = w.get("type")
            x, y = int(w.findtext("x") or 0) + ox, int(w.findtext("y") or 0) + oy
            ww, hh = int(w.findtext("width") or 100), int(w.findtext("height") or 20)
            st = f"left:{x}px;top:{y}px;width:{ww}px;height:{hh}px;"
            if t == "group":
                nm = w.findtext("name") or ""
                c = "#889"
                pvsin = [e.text for e in w.iter("pv_name")]
                if pvsin and pvsin[0] in pvs:
                    c = color_for(pvs[pvsin[0]], order)
                out.append(f'<div class="o grp" style="{st}border-color:{c}"><span style="color:{c}">{esc(nm)}</span></div>')
                # Phoebus places a group's children below its title bar
                walk(w, x + 4, y + 22, nm)
            elif t == "label":
                out.append(f'<div class="o t" title="{esc(w.findtext("text"))}" style="{st}">{esc(w.findtext("text"))}</div>')
            elif t == "action_button":
                pv = w.findtext("pv_name") or ""
                acts = [a.findtext("file") for a in w.iter("action") if a.findtext("file")]
                val = [a.findtext("value") for a in w.iter("action") if a.findtext("value")]
                lab = w.findtext("text") or ""
                if acts:
                    out.append(f'<div class="o lk" title="opens {esc(acts[0])}" style="{st}">{esc(lab)}</div>')
                else:
                    wp = next((a.findtext("pv_name") for a in w.iter("action") if a.findtext("pv_name")), pv)
                    val = val[0] if val else ""
                    c = color_for(pvs.get(wp, ""), order)
                    out.append(f'<div class="o pv w btn" data-pv="{esc(wp)}" title="{esc(wp)} writes {esc(val)}" style="{st}border-color:{c}">{esc(lab)}</div>')
            else:
                pv = w.findtext("pv_name") or ""
                c = color_for(pvs.get(pv, ""), order)
                short = static_suffix(pv).lstrip(":-_")
                if "$(" in short:
                    short = short[short.rindex(")") + 1 :].lstrip(":-_")
                kind = {"textupdate": "r", "led": "r"}.get(t, "w")
                out.append(
                    f'<div class="o pv {kind}" data-pv="{esc(pv)}" title="{esc(pv)} [{esc(t)}]" '
                    f'style="{st}border-color:{c};background:{c}22">{esc(short)}'
                    f'<i>{esc(t)}</i></div>'
                )

    walk(root, 0, 0, "")
    out.append("</div>")
    return "".join(out)


CSS = """
:root{--bg:#f4f4f2;--fg:#222;--muted:#666;--card:#fff;--line:#ccc}
@media (prefers-color-scheme: dark){:root{--bg:#1d1f21;--fg:#e6e6e6;--muted:#aaa;--card:#26282b;--line:#444}}
body{font:13px/1.35 system-ui,sans-serif;margin:0;padding:16px;background:var(--bg);color:var(--fg)}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 6px;border-top:2px solid var(--line);padding-top:12px}
h3{font-size:13px;margin:10px 0 4px;color:var(--muted);font-weight:600}
a{color:#1b6ca8}.cols{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
.col{min-width:300px;flex:1 1 0;overflow-x:auto}
.scr{position:relative;color:#000;outline:1px solid #666;margin-bottom:10px;font-size:11px}
.bob{background:#f5f7fa}
.o{position:absolute;box-sizing:border-box;overflow:hidden;white-space:nowrap}
.t{line-height:1.05;white-space:normal;font-size:11px}
.pv{border:1.5px solid #888;font:10px/1.2 ui-monospace,monospace;padding:0 2px;color:#111;cursor:default}
.pv.w{background:#fff!important;border-width:2.5px}
.pv i{display:none}
.pv.x{background:repeating-linear-gradient(45deg,#fff,#fff 3px,#e88 3px,#e88 6px);border:1.5px dashed #b00}
.btn{text-align:center;background:#eee!important}
.lk{background:#c9d6e8;border:1px solid #567;text-align:center;font-size:11px}
.pip{background:#ece7d6;border:1px dashed #875;font-size:11px;text-align:center}
.chrome{background:#ddd;border:1px solid #aaa;color:#777;text-align:center;font-size:10px;opacity:.75}
.grp{border:2px solid #889;border-radius:3px}
.grp span{position:absolute;top:0;left:4px;font-weight:700;font-size:11px}
.fold{position:absolute;left:0;border-top:2px dashed #06c;z-index:9999;pointer-events:none}
.foldv{position:absolute;top:0;border-left:2px dashed #06c;z-index:9999;pointer-events:none}
.hl{outline:3px solid #ff0!important;z-index:100000!important}
.legend span{display:inline-block;margin:0 10px 4px 0}.legend b{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-2px}
details{background:var(--card);border:1px solid var(--line);padding:6px 10px;margin:6px 0}summary{cursor:pointer;font-weight:600}
ul{margin:4px 0;padding-left:18px}code{font-size:11px}
.note{color:var(--muted)}
"""
JS = """
document.addEventListener('mouseover',e=>{const p=e.target.closest('[data-pv]');
document.querySelectorAll('.hl').forEach(n=>n.classList.remove('hl'));
if(p){document.querySelectorAll('[data-pv="'+CSS.escape(p.dataset.pv).replace(/\\\\/g,'\\\\')+'"]').forEach(n=>n.classList.add('hl'));
document.querySelectorAll('[data-pv]').forEach(n=>{if(n.dataset.pv===p.dataset.pv)n.classList.add('hl')})}});
"""


def li(items) -> str:
    return "<ul>" + "".join(f"<li><code>{esc(x)}</code></li>" for x in items) + "</ul>" if items else '<p class="note">none</p>'


def render_module(module: str, status_failures: dict | None = None) -> dict:
    status_failures = status_failures or {}
    out_dir = CFG.output / module
    rep = json.loads((out_dir / "report.json").read_text())
    val = json.loads((out_dir / "validate.json").read_text()) if (out_dir / "validate.json").exists() else {}
    box = CFG.sandbox / module / "opi"
    parts = [f"<h1>{esc(module)}: EDM screen against generated PVI</h1>"]
    parts.append(
        f'<p><a href="index.html">all modules</a> &middot; release <code>{esc(rep["release"])}</code>. '
        f'{esc(rep.get("release_note", ""))}</p>'
        '<p class="note">Left: every object drawn at its EDM coordinates and colour. Right: the generated <code>.bob</code> at its '
        "coordinates. A PV widget carries the colour of the PVI group it landed in, so colours crossing a frame show a grouping "
        "difference. Thick white box: writable. Tinted box: read-only. Red hatching: on the screen, not in the PVI. Grey: chrome not "
        "converted. Blue dashed line: the window's initial edge; what lies beyond is opened by an expander button. "
        "Hover a PV to highlight it on both sides.</p>"
    )
    summary = {}
    for stem, d in rep["devices"].items():
        if "error" in d:
            parts.append(f"<h2>{esc(stem)}</h2><p>{esc(d['error'])}</p>")
            continue
        fstem = d.get("file_stem", stem)
        if not (out_dir / f"{fstem}.pvi.device.yaml").exists():
            continue  # its entities failed validation
        device = yaml.safe_load((out_dir / f"{fstem}.pvi.device.yaml").read_text())
        pvs, order = group_map(device)
        parts.append(f"<h2>{esc(stem)}</h2>")
        parts.append(
            f"<p>Entity <code>{esc(d['entity'])}</code>, template <code>{esc(d['template'])}</code>, root screen "
            f"<code>{esc(d['screen'])}</code> ({esc(d['how'])}). Macros "
            f"<code>{esc(d['macros'])}</code>. {d['n_placed']} of {d['n_records']} records placed.</p>"
        )
        parts.append('<div class="legend">' + "".join(f'<span><b style="background:{color_for(n, order)}"></b>{esc(n)}</span>' for n in order) + "</div>")
        left, right = [], []
        seen: dict[str, int] = {}
        for i_s, s in enumerate(d["screens"]):
            if i_s >= MAX_SCREENS:
                left.append(f'<p class="note">{len(d["screens"]) - MAX_SCREENS} more screens not drawn</p>')
                break
            fn = s["file"]
            seen[fn] = seen.get(fn, 0) + 1
            try:
                body = draw_edl(s["path"], s["env"], pvs, order, set())
            except Exception as e:  # noqa: BLE001
                body = f'<p class="note">screen not drawn: {esc(e)}</p>'
            head = f"{fn} {esc(s['label'])}"
            if seen[fn] > 1:
                left.append(f"<details><summary>{head} {esc({k: v for k, v in s['env'].items() if '$' not in v})}</summary>{body}</details>")
            else:
                left.append(f"<h3>{head}</h3>{body}")
        # the protected sub-screen is drawn right after the main screen, never cut off
        bobs = sorted(box.glob(f"{fstem}.pvi.bob")) + sorted(box.glob(f"{fstem}_*.pvi.bob"), key=lambda b: (not b.stem.endswith("_ProtectedControls.pvi"), b.name))
        for i, b in enumerate(bobs):
            if i >= MAX_SCREENS:
                right.append(f'<p class="note">{len(bobs) - MAX_SCREENS} more .bob files not drawn</p>')
                break
            body = draw_bob(b, pvs, order)
            if i > 1:
                right.append(f"<details><summary>{esc(b.name)}</summary>{body}</details>")
            else:
                right.append(f"<h3>{esc(b.name)}</h3>{body}")
        parts.append(f'<div class="cols"><div class="col">{"".join(left)}</div><div class="col">{"".join(right)}</div></div>')
        protected = d.get("protected", {})
        if protected:
            parts.append(f'<details open><summary>Moved to Protected Controls ({len(protected)}): <a href="gated-review.html#{esc(module)}">why</a></summary>{li(f"{k}: {v}" for k, v in sorted(protected.items()))}</details>')
        gated = d.get("gated", [])
        parts.append(f"<details><summary>Visibility-gated writes ({len(gated)})</summary>{li(f"{g['pv']}: {g['condition']} on {g['gate_pv']} [{g['screen']}]: {g['handled']}" for g in gated)}</details>")
        dialogs = d.get("dialogs", [])
        parts.append(f"<details><summary>Dialogs ({len(dialogs)})</summary>{li(f"{g['kind']}: {g['dialog']} from {g['screen']}: {g['text']} [{g['handled']}]" for g in dialogs)}</details>")
        parts.append(f"<details open><summary>Judgements ({len(d['judgements'])})</summary>{li(d['judgements'])}</details>")
        parts.append(f"<details><summary>On a screen, not in the database ({len(d['on_screen_not_in_db'])})</summary>{li(f'{k}   ({chr(44).join(v)})' for k, v in d['on_screen_not_in_db'].items())}</details>")
        lo = [f"{x[0]}  [{x[1]}] {x[2]}" for x in d["left_out"]]
        parts.append(f"<details><summary>In the database, on no screen: left out ({len(lo)})</summary>{li(lo)}</details>")
        parts.append(f"<details><summary>Output records the screen only shows: kept read-only ({len(d['readonly_outputs'])})</summary>{li(d['readonly_outputs'])}</details>")
        parts.append(f"<details><summary>Links not followed ({len(d['external'])})</summary>{li(d['external'])}</details>")
        parts.append(f"<details><summary>Notes ({len(d['notes'])})</summary>{li(d['notes'])}</details>")
        summary[stem] = dict(placed=d["n_placed"], records=d["n_records"], judgements=len(d["judgements"]), unmatched=len(d["on_screen_not_in_db"]))
    if rep.get("entity_failures") or status_failures:
        fails = {**rep.get("entity_failures", {}), **status_failures}
        parts.append("<h2>Entities backed out</h2>" + li(f"{a}: {b}" for a, b in fails.items()))
    if rep["no_screen"]:
        parts.append("<h2>Entities with no device screen</h2>" + li(f"{a}: {b}" for a, b in rep["no_screen"]))
    rows = {k: {x: v[x] for x in ("ok", "bobs", "expander", "n_pvi_signals", "n_records_loaded", "generate_matches_generate2", "cls", "reason") if x in v} for k, v in val.get("entities", {}).items()}
    parts.append(f"<h2>Validation</h2><pre>{esc(json.dumps(rows, indent=1))}</pre>")
    page = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PVI review {esc(module)}</title><style>{CSS}</style></head><body>{"".join(parts)}<script>{JS}</script></body></html>'
    rv = CFG.review
    rv.mkdir(parents=True, exist_ok=True)
    (rv / f"{module}.html").write_text(page)
    return summary


def review(modules: list[str]):
    """All written modules, by repo and worst first, then what was not written."""
    status = json.loads((CFG.status / "sweep-status.json").read_text())
    done = [v for v in status.values() if v.get("status") == "done"]
    if modules:
        done = [v for v in done if v["dir"] in modules]
    for st in done:
        try:
            render_module(st["dir"], {k: f"{v['cls']}: {v['reason']}" for k, v in st.get("entity_failures", {}).items()})
        except Exception as e:  # noqa: BLE001
            print("render failed", st["dir"], e)
    body = []
    for repo, folder in CFG.repos.items():
        rows = sorted((v for v in status.values() if v.get("status") == "done" and v["repo"] == repo),
                      key=lambda v: v["placed"] / max(v["records"], 1))
        body.append(f"<h2>{esc(repo)} ({esc(folder.name)}): {len(rows)} written</h2><table><tr><th>module</th><th>placed</th><th>share</th><th>left out</th><th>screen only</th>"
                    "<th>gated writes</th><th>protected</th><th>dialogs</th><th>judgements</th><th>screen mapping</th><th>release</th></tr>")
        for v in rows:
            share = 100 * v["placed"] / max(v["records"], 1)
            body.append(f'<tr><td><a href="{esc(v["dir"])}.html">{esc(v["dir"])}</a></td><td>{v["placed"]}/{v["records"]}</td><td>{share:.0f}%</td><td>{v["left_out"]}</td>'
                        f'<td>{v["screen_only"]}</td><td>{v["gated"]}</td><td>{v.get("protected", 0)}</td><td>{v["dialogs"]}</td><td>{v["judgements"]}</td><td>{esc(", ".join(v["how"]))}</td>'
                        f'<td>{esc(Path(v["release"]).name)}: {esc(v["release_how"])}</td></tr>')
        body.append("</table>")
        others = sorted((v for v in status.values() if v.get("status") in ("failed", "skipped") and v["repo"] == repo), key=lambda v: (v["status"], v["cls"], v["dir"]))
        body.append("<h3>Not written</h3><table><tr><th>module</th><th>outcome</th><th>class</th><th>reason</th></tr>")
        for v in others:
            body.append(f'<tr><td>{esc(v["dir"])}</td><td>{esc(v["status"])}</td><td>{esc(v["cls"])}</td><td>{esc(v.get("reason", ""))}</td></tr>')
        body.append("</table>")
    page = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PVI sweep review</title>'
            f"<style>{CSS} table{{border-collapse:collapse}}td,th{{border:1px solid var(--line);padding:3px 8px;text-align:left}}</style></head><body>"
            f'<h1>PVI sweep: grouping from EDM screens</h1><p class="note">Local files only. Worst first by share of records placed. Not reviewed by a person. <a href="gated-review.html">Gated writes, classified</a>.</p>{"".join(body)}</body></html>')
    CFG.review.mkdir(parents=True, exist_ok=True)
    (CFG.review / "index.html").write_text(page)
