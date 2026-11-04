#!/usr/bin/env python3
"""Generate *.pvi.device.yaml + entity `pvi:` sections from EDM screens.

Deterministic. Per-module inputs live in <overrides>/<module>.yaml, and every
override is a judgement that is reported, so a judgement is never silent.
Outputs for review go to <output>/<module>/; --write also updates the support repo.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from dbparse import INPUT, OUTPUT, Db, default_of, macros_in, parse_db, static_suffix  # noqa: E402
from edl import (  # noqa: E402
    Obj,
    Screen,
    as_list,
    expand,
    gate_conditions,
    links,
    parse_edl,
    parse_symbols,
    pv_uses,
    text_lines,
    text_of,
)
from fielddefs import STRINGISH, field_type, left_out_why  # noqa: E402
from protect import MOVED, SUB_LABEL, load_classes, move, on_main, targets_of, verify_move  # noqa: E402
from release import db_search_path, deps, find_db  # noqa: E402
from settings import CFG  # noqa: E402

DROP_CLASSES = {"activeExitButtonClass", "shellCmdClass"}
NEAR_TEXT = 120  # pixels: a text further from a bare button than this is not its label
UNIT_GAP = 40  # pixels
REGEN_NOTE = "# Generated from that screen. Hand edits may be overwritten by regeneration."


def pascal(s: str) -> str:
    """Any text to a pvi PascalStr: ^([A-Z][a-z0-9]*)*$."""
    parts = re.findall(r"[A-Za-z0-9]+", s)
    out = ""
    for p in parts:
        # keep existing camel humps only when mixed case
        if re.search(r"[a-z]", p) and re.search(r"[A-Z]", p):
            sub = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])|[0-9]+", p)
        else:
            sub = [p]
        for t in sub:
            out += t[:1].upper() + t[1:].lower()
    if not out or not out[0].isalpha():
        out = "N" + out
    return out


def clean_label(s: str) -> str:
    # `$(NAME=text)` shows its text unless the macro is set
    s = re.sub(r"\$\(\w+=([^()]*)\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip().rstrip(":").strip()


LONG_LABEL = 60
MACRO_REF = re.compile(r"\$\(([^()]*)\)")


def junk_label(s: str) -> bool:
    """A label of macros that says nothing on a screen: `P $(P) R $(Q)`, `$(a)$(b)`,
    `$(P$(Q):NOMOTOR)`, `$(dev):NAME`. `Channel $(CHAN_NUM)` and `LVDT$(id)` say something."""
    if "$(" not in s:
        return False
    if re.search(r"\$\([^()]*\$\(", s) or re.search(r"\):", s):
        return True
    rest = MACRO_REF.sub(" ", s)
    if not re.search(r"[A-Za-z]", rest):
        return True
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rest)
    pairs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s+\$\(([^()]*)\)", s)
    named = [w for w, m in pairs if len(w) == 1 or w.lower() == m.lower()]
    return sorted(named) == sorted(words)


def shorten(s: str, limit: int = LONG_LABEL) -> str:
    """A label cut to size: the tail of a ` / ` path, otherwise at a word."""
    if len(s) <= limit:
        return s
    if " / " in s:
        parts = s.split(" / ")
        tail = parts[-1]
        for p in reversed(parts[:-1]):
            if len(p) + len(tail) + 10 > limit:
                break
            tail = f"{p} / {tail}"
        if len(tail) + 6 <= limit:
            return ".. / " + tail
    cut = s[: limit - 4].rsplit(" ", 1)[0].rstrip(" ,;:/-")
    return f"{cut} ..."


def list_label(items: list[str], limit: int = LONG_LABEL) -> str:
    """Column text as one label: whole items, as many as fit. Bare bit numbers say nothing."""
    words = [i for i in items if i and not re.fullmatch(r"[\d\s.+-]*", i)] or [i for i in items if i]
    out = ""
    for i, w in enumerate(words):
        more = out + (", " if out else "") + w
        if len(more) + (4 if i + 1 < len(words) else 0) > limit:
            return f"{out} ..." if out else shorten(w, limit)
        out = more
    return out


def overlap_area(a: Obj, b: Obj) -> int:
    w = min(a.x2, b.x2) - max(a.x, b.x)
    h = min(a.y2, b.y2) - max(a.y, b.y)
    return w * h if w > 0 and h > 0 else 0


def own_button_text(o: Obj, screen: str = "") -> str:
    """The text EDM draws on a message button itself; a blank label is no label. EDM
    draws offLabel at rest and onLabel only while the button is held. A toggle stays
    held, so onLabel names its press value."""
    for k in ("onLabel", "offLabel") if o.get("toggle") or screen in CFG.held_label_screens else ("offLabel", "onLabel"):
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def release_text(label: str, pv: str) -> str:
    """The action for what a momentary button writes on release. Letting go of a jog
    ends the move; on anything else the second write only undoes the press value."""
    word = "stop" if re.search(r"\.JOG[FR]$", pv) else "release"
    return f"{label} {word}".strip()


def value_text(v) -> str:
    """A press value that reads as words (`In`, `Out`); a number says nothing."""
    return v.strip() if isinstance(v, str) and re.search(r"[A-Za-z]", v) and "$(" not in v else ""


TEXT_WIDGETS = {"TextupdateClass", "activeXTextDspClass", "activeXTextDspClass:noedit", "TextentryClass", "activeMenuButtonClass"}


def gate_of(o: Obj) -> tuple:
    """What decides whether a widget is drawn, with its range."""
    for pv, pre in (("visPv", "vis"), ("groupVisPv", "groupVis")):
        if o.get(pv):
            return (o.get(pv), o.get(pre + "Min"), o.get(pre + "Max"), o.get(pre + "Invert"))
    return ()


def is_overlay(t: Obj, widgets: list[Obj]) -> bool:
    """Text that shows a state rather than naming a row: drawn only under another
    condition than the widgets beside it, or stacked on top of a text widget."""
    gate = gate_of(t)
    if gate:
        beside = [w for w in widgets if min(t.y2, w.y2) - max(t.y, w.y) >= 0.5 * min(t.h or 1, w.h or 1)]
        return not any(gate_of(w) == gate for w in beside)
    return any(
        w.cls in TEXT_WIDGETS and t.x >= w.x - 2 and t.y >= w.y - 2 and overlap_area(t, w) >= 0.5 * max(w.w * w.h, 1)
        for w in widgets
    )


def norm_pv(suffix: str) -> str:
    """Name with setpoint/readback decoration removed, for pairing."""
    s = suffix.upper()
    s = re.sub(r"[:_]?RBV$", "", s)
    s = re.sub(r"_S(?=\d|$)", "", s)
    s = s.replace("GET", "SET")
    s = s.replace("SET", "")
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


@dataclass
class Use:
    """One PV-bearing widget, expanded into db macro space."""

    pv: str  # as it appears on screen, expanded
    dbpv: str | None  # record name in the db, or None
    fieldname: str  # record field after a dot, '' otherwise
    role: str
    obj: Obj
    caption: str = ""  # text drawn on this button by another widget
    caption_static: bool = False  # the caption is that text, not a stand-in for an update
    on_button: bool = False  # a .DESC drawn on a button: that button's caption
    icon: str = ""  # what an image drawn on this button says it does


@dataclass
class Row:
    y1: float
    y2: float
    uses: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    links: list = field(default_factory=list)
    heading: str = ""  # text above a column of texts on this row


@dataclass
class Ctx:
    module: str
    release: Path
    dbs: list[Db]
    records: dict
    env: dict
    roots: dict  # screen file -> device stem, for cross-device references
    subst: dict
    notes: list = field(default_factory=list)
    judgements: list = field(default_factory=list)
    unmatched: dict = field(default_factory=dict)  # pv -> screens
    decor: set = field(default_factory=set)
    screens: list = field(default_factory=list)  # (file, env, device-stem) drawn
    external: list = field(default_factory=list)
    used: dict = field(default_factory=dict)  # record -> first group
    group_names: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    skip_links: set = field(default_factory=set)
    readonly: list = field(default_factory=list)
    device_macros: set = field(default_factory=set)
    device_refs: dict = field(default_factory=dict)
    visiting: list = field(default_factory=list)
    widget_group: dict = field(default_factory=dict)
    prefix: str = ""
    sweep: bool = False  # an override file of a module's own runs with this off
    gated: list = field(default_factory=list)
    link_gates: list = field(default_factory=list)  # gates of the links followed to this screen
    gated_refs: list = field(default_factory=list)  # gated links to a device of its own
    dialogs: list = field(default_factory=list)
    root_macros: dict = field(default_factory=dict)  # screen -> {screen macro: value}
    env_cur: dict = field(default_factory=dict)
    link_labels: dict = field(default_factory=dict)
    dropped_reads: set = field(default_factory=set)
    fields_left: dict = field(default_factory=dict)  # screen pv -> why it stays out
    merged_buttons: dict = field(default_factory=dict)  # pv -> actions of its merged panel
    momentary: dict = field(default_factory=dict)  # pv -> text of each button writing it on press and on release
    buttons_covered: dict = field(default_factory=dict)  # pv -> values and the other widget that can write them
    no_field_records: dict = field(default_factory=dict)  # record -> why its fields stay out


def literal_macros(label: str, ctx: Ctx) -> str:
    """A label's macros that the screen was opened with a real value for take that value."""
    return expand(label, {k: v for k, v in ctx.env_cur.items() if "$(" not in str(v)})


def data_path(ctx: Ctx, fname: str) -> Path | None:
    f = fname if fname.endswith(".edl") else fname + ".edl"
    f = ctx.subst.get(f, f)
    p = ctx.release / "data" / f
    if p.exists():
        return p
    for sub in ctx.release.glob("*App/opi/edl"):
        if (sub / f).exists():
            return sub / f
    if ctx.sweep:
        for _, dep in deps(ctx.release):
            if (dep / "data" / f).exists():
                return dep / "data" / f
    return None


def screen_extent(s: Screen) -> tuple[int, int]:
    """Screen size, including regions opened by a window-resize shell button."""
    w, h = s.w, s.h
    for o in s.objects:
        if o.cls != "shellCmdClass":
            continue
        for c in as_list(o.get("command")):
            if m := re.search(r"windowsize\s+<WINID>\s+(\d+)\s+(\d+)", c):
                w, h = max(w, int(m.group(1))), max(h, int(m.group(2)))
            if "dls-windowsize" in c:
                for k, v in re.findall(r"--([xy])\d=(\d+)", c):
                    if k == "x":
                        w = max(w, int(v))
                    else:
                        h = max(h, int(v))
    return w, h


def resolve(ctx: Ctx, pv: str) -> tuple[str | None, str]:
    """Screen PV to (record name, field). Exact first, then by static suffix."""
    base, dot, fld = pv.partition(".")
    if base in ctx.records:
        return base, fld
    suf = static_suffix(base)
    if suf and suf != base:
        hits = [r for r in ctx.records if static_suffix(r) == suf]
        if len(hits) == 1:
            ctx.notes.append(f"screen PV `{base}` matched record `{hits[0]}` by suffix: macros differ")
            return hits[0], fld
    if ctx.sweep and (hit := match_tail(base, ctx.records)):
        ctx.notes.append(f"screen PV `{base}` matched record `{hit}` by the text after its macros")
        return hit, fld
    return None, fld


MACRO_RUN = re.compile(r"^(?:\$\(\w+\)[:\-_.]?)+")


def match_tail(pv: str, records) -> str | None:
    """`$(A):$(B):FOO` to the one record ending `:FOO`, where macros differ in number."""
    if not MACRO_RUN.match(pv):
        return None
    tail = MACRO_RUN.sub("", pv)
    if len(tail) < 3:
        return None
    hits = [r for r in records if "$(" in r and MACRO_RUN.sub("", r) == tail]
    return hits[0] if len(hits) == 1 else None


def frames_of(s: Screen, widgets: list[Obj], ctx: Ctx, fname: str) -> list[dict]:
    W, H = screen_extent(s)
    rects = [
        o
        for o in s.objects
        if o.cls == "activeRectangleClass"
        and o.w >= 40
        and o.h >= 24
        and not o.get("invisible")
        and not (o.w >= 0.97 * W and o.h >= 0.97 * H)
    ]
    frames = [r for r in rects if any(r.contains(w) for w in widgets)]
    texts = [o for o in s.objects if o.cls == "activeXTextClass" and text_of(o) and not o.get("visPv")]
    out = []
    for fr in frames:
        # a frame nested in another is layout decoration: only outermost count
        if any(g is not fr and g.w * g.h > fr.w * fr.h and g.contains(fr, 4) for g in frames):
            continue
        cands = []
        for t in texts:
            crosses = t.y < fr.y <= t.y2 + 2
            inside_x = fr.x - 2 <= t.x and t.x < fr.x2
            if crosses and inside_x and t.h <= 30:
                cands.append(t)
        cands.sort(key=lambda t: (t.y, t.x))
        head = cands[0] if cands else None
        title = literal_macros(clean_label(text_of(head)), ctx) if head else ""
        out.append(dict(rect=fr, head=head, title="" if junk_label(title) else title))
    # An unheaded frame that sits beside a headed one of the same height is its
    # continuation, so the two share the heading.
    for f in out:
        if f["title"]:
            continue
        for g in out:
            if g is f or not g["title"]:
                continue
            a, b = f["rect"], g["rect"]
            if abs(a.y - b.y) <= 4 and abs(a.h - b.h) <= 8:
                f["title"] = g["title"]
                f["head"] = g["head"]
                ctx.judgements.append(
                    f"{fname}: frame at x={a.x} has no heading; merged with `{g['title']}` beside it"
                )
                break
    return out


def layout_screen(ctx: Ctx, path: Path, env: dict, depth: int = 0) -> list[dict]:
    """A screen to a list of group dicts: {title, rows, frame}."""
    s = parse_edl(path)
    fname = path.name
    W, H = screen_extent(s)
    title_objs = [
        o
        for o in s.objects
        if o.cls == "activeXTextClass" and o.y <= 6 and o.w >= 0.6 * max(s.w, 1)
    ]
    uses: list[Use] = []
    link_objs: list[dict] = []
    offscreen = 0
    objs = []
    for o in s.objects:
        if o.cls in DROP_CLASSES:
            continue
        if o.x >= W or o.y >= H:
            offscreen += 1
            for u in pv_uses(o):
                ctx.notes.append(
                    f"{fname}: `{expand(u.pv, env)}` widget sits outside the window at ({o.x},{o.y}): ignored"
                )
            continue
        objs.append(o)
    pv_widgets: list[Obj] = []
    for o in objs:
        for u in pv_uses(o):
            pv = expand(u.pv, env)
            if u.role == "decor":
                ctx.decor.add(pv.partition(".")[0])
                continue
            rec, fld = resolve(ctx, pv)
            role = "read" if u.role == "led" else u.role
            if role == "write":
                full = field_pv(rec, fld) if rec else pv
                for gate, cond in gate_conditions(o, env):
                    ctx.gated.append(dict(pv=full, field=fld, screen=fname, gate_pv=gate, condition=cond,
                                          widget=o.cls, in_db=rec is not None))
                for gate, cond in ctx.link_gates:
                    ctx.gated.append(dict(pv=full, field=fld, screen=fname, gate_pv=gate, condition=f"{cond}, on the link to this screen",
                                          widget=o.cls, in_db=rec is not None, via_link=True))
                if o.get("password"):
                    ctx.gated.append(dict(pv=full, field=fld, screen=fname, gate_pv="", condition="widget asks for a password",
                                          widget=o.cls, in_db=rec is not None))
            if rec is None:
                ctx.unmatched.setdefault(pv, set()).add(fname)
                continue
            uses.append(Use(pv=pv, dbpv=rec, fieldname=fld, role=role, obj=o))
            pv_widgets.append(o)
        for ln in links(o):
            ln["env"] = {**env, **parse_symbols(ln["symbols"], env)}
            ln["obj"] = o
            ln["gates"] = gate_conditions(o, env)
            link_objs.append(ln)
            pv_widgets.append(o)
    # a string record drawn exactly over a related-display button is its caption
    for ln in link_objs:
        b = ln["obj"]
        for u in list(uses):
            o = u.obj
            rec = ctx.records[u.dbpv]
            if (o.x, o.y, o.w, o.h) == (b.x, b.y, b.w, b.h) and rec.rtype.startswith("string") and not u.fieldname:
                ln["caption"] = clean_label(default_of(rec.fields.get("VAL", "")))
                uses.remove(u)
    # a meter or bar beside a text showing the same record is the same signal
    graphical = {"activeMeterClass", "activeLogMeterClass", "activeBarClass"}
    texted = {u.dbpv for u in uses if u.obj.cls not in graphical and not u.fieldname}
    uses = [u for u in uses if not (u.obj.cls in graphical and u.dbpv in texted)]
    # a gated bit display of a record shown as text elsewhere is that text's other variant
    worded = {u.dbpv for u in uses if u.obj.cls in TEXT_WIDGETS and not u.fieldname}
    uses = [u for u in uses if not (u.obj.cls == "ByteClass" and gate_of(u.obj) and u.dbpv in worded and not u.fieldname)]
    captions = attach_captions(ctx, objs, uses, env)
    for u in uses:
        gates = [g for g in (u.obj.get("visPv"), u.obj.get("groupVisPv")) if g]
        if u.role == "write" and gates:
            names = ", ".join(f"`{expand(g, env)}`" for g in gates)
            ctx.judgements.append(
                f"{fname}: write to `{u.dbpv}` is only visible when {names} allow: "
                "the condition is lost in PVI, which always shows it"
            )
    frames = frames_of(s, pv_widgets, ctx, fname)
    heads = {id(f["head"]) for f in frames if f["head"]} | {id(t) for t in title_objs}
    texts = [
        o
        for o in objs
        if o.cls == "activeXTextClass" and text_of(o) and not o.get("visPv") and id(o) not in heads and id(o) not in captions
    ]
    drawn = [u.obj for u in uses]
    for t in [t for t in texts if is_overlay(t, drawn)]:
        texts.remove(t)
        ctx.notes.append(f"{fname}: text `{clean_label(text_of(t))}` is a state overlay: not used as a label")

    def frame_of(o: Obj) -> dict | None:
        best = None
        for f in frames:
            if f["rect"].contains(o):
                best = f
        return best

    # group key: heading text, so that split frames sharing one heading merge
    groups: dict[str, dict] = {}

    def group_for(o: Obj) -> dict:
        f = frame_of(o)
        if f is None:
            key = "__top__"
            order = (False, o.y, o.x)
            title = ""
        else:
            key = f["title"] or f"__frame{f['rect'].x}_{f['rect'].y}__"
            order = (f["rect"].x > W * 0.55, f["rect"].y, f["rect"].x)
            title = f["title"]
        g = groups.get(key)
        if g is None:
            g = groups[key] = dict(key=key, title=title, order=order, items=[], texts=[], links=[])
        return g

    for u in uses:
        group_for(u.obj)["items"].append(u)
    for ln in link_objs:
        group_for(ln["obj"])["links"].append(ln)
    for t in texts:
        f = frame_of(t)
        if f is None:
            if "__top__" in groups:
                groups["__top__"]["texts"].append(t)
        else:
            key = f["title"] or f"__frame{f['rect'].x}_{f['rect'].y}__"
            if key in groups:
                groups[key]["texts"].append(t)

    out = []
    for g in sorted(groups.values(), key=lambda g: g["order"]):
        g["rows"] = make_rows(g["items"], g["texts"], g["links"])
        out.append(g)
    return out


ICON_TEXT = {"refresh": "Refresh"}


def not_at_rest(t: Obj) -> bool:
    """True for a text its gate hides while the gate PV reads 0."""
    gate = gate_of(t)
    if not gate:
        return False
    pv, lo, hi, invert = gate
    try:
        inside = float(lo or 0) <= 0 < float(hi or 0)
    except ValueError:
        return False
    return inside == bool(invert)


def attach_captions(ctx: Ctx, objs: list[Obj], uses: list[Use], env: dict) -> set[int]:
    """A button with no label of its own is captioned by what is drawn on it: a static
    text, or a .DESC whose default (else the record's name) stands for the update."""
    used: set[int] = set()
    for u in uses:
        o = u.obj
        if u.role != "write" or o.cls != "activeMessageButtonClass" or own_button_text(o):
            continue
        for t in objs:
            if t.cls == "activePngClass" and overlap_area(t, o) >= 0.6 * max(t.w * t.h, 1):
                u.icon = ICON_TEXT.get(Path(str(t.get("file") or "")).stem.lower(), "")
        on = [
            t
            for t in objs
            if t.cls == "activeXTextClass" and text_of(t) and not t.get("visPv") and overlap_area(t, o) >= 0.6 * max(t.w * t.h, 1)
        ]
        if on:
            on.sort(key=lambda t: (t.y, t.x, not_at_rest(t)))
            # texts stacked on one spot are variants, shown one at a time: the one drawn
            # at rest names the button, the others name a state
            on = [t for i, t in enumerate(on) if not any(overlap_area(t, b) >= 0.5 * max(min(t.w * t.h, b.w * b.h), 1) for b in on[:i])]
            u.caption = shorten(clean_label(" ".join(expand(text_of(t), env) for t in on)))
            u.caption_static = True
            used.update(id(t) for t in on)
            continue
        for d in uses:
            if d.fieldname == "DESC" and overlap_area(d.obj, o) >= 0.6 * max(d.obj.w * d.obj.h, 1):
                d.on_button = True
                u.caption = clean_label(default_of(ctx.records[d.dbpv].fields.get("DESC", ""))) or suffix_of(d.dbpv)
                break
    return used


def stacked(texts: list[Obj]) -> bool:
    """Two or more texts one above the other, in one column."""
    ordered = sorted(texts, key=lambda t: t.y)
    return any(
        b.y >= a.y2 - 2 and min(a.x2, b.x2) > max(a.x, b.x)
        for i, a in enumerate(ordered)
        for b in ordered[i + 1 :]
    )


def split_lines(t: Obj) -> list[Obj]:
    """A multi-line text as one text per item, each where EDM draws it. Where blank
    lines space the items out, lines with no blank between them are one wrapped item."""
    lines = text_lines(t)
    step = t.h / len(lines)
    spaced = any(not ln for ln in lines) and any(a and b for a, b in zip(lines, lines[1:]))
    items: list[tuple[int, int, str]] = []  # first line, line count, text
    for i, line in enumerate(lines):
        if not line:
            continue
        if spaced and items and lines[i - 1]:
            first, n, text = items[-1]
            items[-1] = (first, n + 1, f"{text} {line}")
        else:
            items.append((i, 1, line))
    return [
        replace(t, y=round(t.y + first * step), h=max(round(n * step), 1), props={**t.props, "value": text})
        for first, n, text in items
    ]


def texts_by_line(texts: list[Obj], rows: list[Row]) -> list[Obj]:
    """Multi-line text that runs across several rows, or is too long for one label, is
    a column of labels. Lines that fit one row are a label wrapped to fit its box."""
    out: list[Obj] = []
    for t in texts:
        all_lines = text_lines(t)
        lines = [ln for ln in all_lines if ln]
        spans = sum(1 for r in rows if min(r.y2, t.y2) - max(r.y1, t.y) >= 0.5 * max(r.y2 - r.y1, 1))
        # two lines with no gap are one label wrapped across a read and a write row
        column = len(lines) >= 3 or len(all_lines) > len(lines)
        if len(lines) >= 2 and ((column and spans >= 2) or len(" ".join(lines)) > LONG_LABEL):
            out.extend(split_lines(t))
        else:
            out.append(t)
    return out


def assign_texts(rows: list[Row], texts: list[Obj]) -> list[Obj]:
    """Each text to the row it overlaps most; returns those that fit no row."""
    orphans = []
    for t in texts:
        best, bo = None, 0.0
        for r in rows:
            ov = min(r.y2, t.y2) - max(r.y1, t.y)
            frac = ov / max(min(r.y2 - r.y1, t.h), 1)
            if frac > bo:
                best, bo = r, frac
        if best is not None and bo >= 0.45:
            best.texts.append(t)
        else:
            orphans.append(t)
    return orphans


def rows_of(entries: list[tuple]) -> list[Row]:
    rows: list[Row] = []
    for obj, kind, val in entries:
        hit = None
        for r in rows:
            ov = min(r.y2, obj.y2) - max(r.y1, obj.y)
            if ov >= 0.5 * min(r.y2 - r.y1 or 1, obj.h or 1):
                hit = r
                break
        if hit is None:
            hit = Row(obj.y, obj.y2)
            rows.append(hit)
        else:
            hit.y1, hit.y2 = min(hit.y1, obj.y), max(hit.y2, obj.y2)
        (hit.uses if kind == "use" else hit.links).append(val)
    return rows


def split_tall_rows(rows: list[Row]) -> list[Row]:
    """A tall widget beside a column of labels had merged the rows it spans. They are
    separate rows, and the tall widget joins the top one."""
    out: list[Row] = []
    for r in rows:
        objs = [u.obj for u in r.uses] + [ln["obj"] for ln in r.links]
        hs = sorted(o.h for o in objs)
        med = hs[len(hs) // 2] if hs else 0
        # only a widget with two or more labels stacked to its left has merged rows
        tall = [
            o
            for o in objs
            if o.h >= 1.5 * med and o.h > med + 8 and stacked([t for t in r.texts if t.x2 <= o.x + 6 and min(t.y2, o.y2) > max(t.y, o.y)])
        ]
        if not tall or len(objs) < 3:
            out.append(r)
            continue
        entries = [(u.obj, "use", u) for u in r.uses if u.obj not in tall]
        entries += [(ln["obj"], "link", ln) for ln in r.links if ln["obj"] not in tall]
        entries.sort(key=lambda e: (e[0].cy, e[0].x))
        parts = rows_of(entries)
        if len(parts) < 2:
            out.append(r)
            continue
        parts.sort(key=lambda p: p.y1)
        for u in r.uses:
            if u.obj in tall:
                next((p for p in parts if p.y2 > u.obj.y), parts[0]).uses.append(u)
        for ln in r.links:
            if ln["obj"] in tall:
                next((p for p in parts if p.y2 > ln["obj"].y), parts[0]).links.append(ln)
        assign_texts(parts, r.texts)
        out.extend(parts)
    return out


def column_headings(rows: list[Row], orphans: list[Obj]):
    """A row with a column of texts is named by a text directly above that column."""
    for r in rows:
        col = [t for t in r.texts if any(u.obj.x >= t.x2 - 6 for u in r.uses)]
        if not stacked(col):
            continue
        top = min(t.y for t in col)
        x1, x2 = min(t.x for t in col), max(t.x2 for t in col)
        above = [t for t in orphans if t.y2 <= top + 2 and top - t.y2 <= 24 and min(t.x2, x2) > max(t.x, x1)]
        if above:
            r.heading = clean_label(text_of(max(above, key=lambda t: t.y)))


def make_rows(items: list[Use], texts: list[Obj], lns: list[dict]) -> list[Row]:
    entries = [(u.obj, "use", u) for u in items] + [(ln["obj"], "link", ln) for ln in lns]
    entries.sort(key=lambda e: (e[0].cy, e[0].x))
    rows = rows_of(entries)
    orphans = assign_texts(rows, texts_by_line(texts, rows))
    rows = split_tall_rows(rows)
    column_headings(rows, orphans)
    rows.sort(key=lambda r: r.y1)
    # A row of text only, directly above a row of widgets it lines up with,
    # supplies column headings.
    for r in rows:
        r.header = None  # type: ignore[attr-defined]
    for r in rows:
        above = [t for t in orphans if t.y2 <= r.y1 + 2 and r.y1 - t.y2 <= 24]
        if len(above) < 2:
            continue
        cols = sorted({round(u.obj.cx) for u in r.uses})
        if len(cols) < 2:
            continue
        head = []
        for c in cols:
            m = [t for t in above if t.x - 4 <= c <= t.x2 + 4]
            head.append(clean_label(text_of(m[0])) if m else "")
        if sum(1 for h in head if h) >= 2:
            r.header = head  # type: ignore[attr-defined]
            for t in above:
                orphans.remove(t)
            break
    return rows


def field_pv(rec: str, fld: str) -> str:
    """Record and field as one PV; VAL is the record itself."""
    return f"{rec}.{fld}" if fld and fld != "VAL" else rec


def record_of(ctx: Ctx, pv: str):
    return ctx.records[pv.partition(".")[0]]


def widget_to_read(ctx: Ctx, pv: str, objs: list | None = None) -> dict:
    rec = record_of(ctx, pv)
    if "." not in pv:
        return read_widget(rec)
    if any(o.cls in ("activeCircleClass", "activeRectangleClass") for o in objs or []):
        return {"type": "LED"}
    if field_type(rec.rtype, pv.partition(".")[2], ctx.release) in STRINGISH:
        return {"type": "TextRead", "format": "string"}
    return {"type": "TextRead"}


def widget_to_write(ctx: Ctx, pv: str) -> dict:
    rec = record_of(ctx, pv)
    kind = field_type(rec.rtype, pv.partition(".")[2], ctx.release)
    if kind == "DBF_MENU":
        return {"type": "ComboBox"}
    if kind in STRINGISH:
        return {"type": "TextWrite", "format": "string"}
    return {"type": "TextWrite"}


def read_widget(rec) -> dict:
    t = rec.rtype
    if t in ("bi", "bo"):
        return {"type": "LED"}
    if t in ("stringin", "stringout", "lsi", "lso"):
        return {"type": "TextRead", "format": "string"}
    if t in ("waveform", "aai") and rec.fields.get("FTVL", "") in ("CHAR", "UCHAR"):
        return {"type": "TextRead", "format": "string"}
    if t in ("waveform", "aai"):
        return {"type": "ArrayTrace", "axis": "x"}
    return {"type": "TextRead"}


def write_widget(rec) -> dict:
    t = rec.rtype
    if t in ("bo", "bi"):
        return {"type": "ToggleButton"}
    if t in ("mbbo", "mbbi"):
        return {"type": "ComboBox"}
    if t in ("stringout", "lso"):
        return {"type": "TextWrite", "format": "string"}
    if t in ("waveform", "aao") and rec.fields.get("FTVL", "") in ("CHAR", "UCHAR"):
        return {"type": "TextWrite", "format": "string"}
    return {"type": "TextWrite"}


def suffix_of(rec_name: str, prefix_macros: str = "") -> str:
    s = static_suffix(rec_name).lstrip(":-_")
    if s == "":
        s = rec_name
    # names such as $(dom)-VA-GAUGE-$(id):P keep what follows the last macro
    if "$(" in s:
        s = s[s.rindex(")") + 1 :].lstrip(":-_") or s
    return s


def unique_name(ctx: Ctx, base: str, key: str) -> str:
    n = pascal(base)
    if n not in ctx.names or ctx.names[n] == key:
        ctx.names[n] = key
        return n
    i = 2
    while f"{n}{i}" in ctx.names and ctx.names[f"{n}{i}"] != key:
        i += 1
    ctx.names[f"{n}{i}"] = key
    return f"{n}{i}"


def row_components(ctx: Ctx, row: Row, fname: str, gname: str, placed: dict) -> list[dict]:
    """A row of widgets to pvi components, with label from the row's text."""
    uses = sorted(row.uses, key=lambda u: u.obj.x)
    # label widgets: a .DESC on the row is that row's label
    label = ""
    real: list[Use] = []
    desc_label = ""
    for u in uses:
        if u.fieldname == "DESC":
            desc = ctx.records[u.dbpv].fields.get("DESC", "")
            if not u.on_button:
                desc_label = clean_label(default_of(desc)) or suffix_of(u.dbpv)
            continue
        if u.fieldname and u.fieldname != "VAL":
            why = ctx.no_field_records.get(u.dbpv) or left_out_why(ctx.records[u.dbpv].rtype, u.fieldname, ctx.release)
            if why:
                ctx.decor.add(u.dbpv)
                ctx.fields_left[u.pv] = why
                ctx.notes.append(f"{fname}: `{u.pv}` left out: {why}")
                continue
        real.append(u)
    first_x = min((u.obj.x for u in real), default=None)
    texts = sorted(row.texts, key=lambda t: t.x)
    if first_x is not None:
        left = [t for t in texts if t.x2 <= first_x + 6 or t.cx < first_x]
        right = [t for t in texts if t not in left]
    else:
        left, right = texts, []
    first = min(real, key=lambda u: u.obj.x, default=None)
    if first is not None and first.obj.cls == "activeMessageButtonClass" and not own_button_text(first.obj) and not first.caption:
        # a text well away from a bare button is not about that button
        left = [t for t in left if first_x - t.x2 <= NEAR_TEXT]
    if stacked(left):
        label = row.heading or list_label([clean_label(text_of(t)) for t in sorted(left, key=lambda t: (t.y, t.x))])
    elif left:
        label = clean_label(" ".join(text_of(t) for t in left))
    elif desc_label:
        label = desc_label
    label = literal_macros(label, ctx)
    if junk_label(label):
        label = ""
    # a unit sits just after a widget; a short text further on belongs to something else
    units = [clean_label(text_of(t)) for t in right if len(text_of(t)) <= 8 and any(0 <= t.x - u.obj.x2 <= UNIT_GAP for u in real)]
    if label and units and not stacked(left):
        label = f"{label} ({units[0]})"

    # one entry per record: a meter and a text showing the same record collapse
    by_rec: dict[str, dict] = {}
    press: dict[str, list[tuple[str, str]]] = {}
    second: dict[str, list[tuple[str, str]]] = {}
    for u in real:
        key = field_pv(u.dbpv, u.fieldname)
        d = by_rec.setdefault(key, dict(rec=key, read=False, write=False, x=u.obj.x, objs=[], caption="", static=False))
        d["x"] = min(d["x"], u.obj.x)
        d["objs"].append(u.obj)
        if u.role == "write":
            d["write"] = True
            if u.obj.cls == "activeMessageButtonClass":
                v = u.obj.get("pressValue") or u.obj.get("releaseValue")
                lab = own_button_text(u.obj, fname) or u.caption or u.icon or value_text(v)
                d["icon"] = d.get("icon") or bool(u.icon and lab == u.icon)
                press.setdefault(key, []).append((lab, str(v) if v is not None else "1"))
                off = u.obj.get("releaseValue")
                if u.obj.get("toggle") and off is not None and str(off) != str(v):
                    # a toggle's second press is a button of its own
                    second.setdefault(key, []).append((str(u.obj.get("offLabel") or "").strip() or value_text(off), str(off)))
                elif off is not None and str(off) != str(v):
                    # held on EDM: what the release writes is a button of its own, except
                    # on .PROC, where any write processes the record and repeats the press
                    if u.fieldname != "PROC":
                        second.setdefault(key, []).append((release_text(lab, key), str(off)))
                    ctx.momentary.setdefault(key, []).append(lab)
                d["caption"] = d["caption"] or u.caption
                d["static"] = d["static"] or u.caption_static
        else:
            d["read"] = True
    ordered = sorted(by_rec.values(), key=lambda d: d["x"])
    # pair writes with reads on the row, by name
    writes = [d for d in ordered if d["write"]]
    reads = [d for d in ordered if d["read"] and not d["write"]]
    pairs = []
    for w in writes:
        nw = norm_pv(suffix_of(w["rec"]))
        # a field never pairs by name: it is a part of a record, not its readback
        m = None if "." in w["rec"] else next((r for r in reads if "." not in r["rec"] and norm_pv(suffix_of(r["rec"])) == nw), None)
        if m is None and len(writes) == 1 and len(reads) == 1 and "." not in w["rec"] and "." not in reads[0]["rec"]:
            a, b = suffix_of(w["rec"]), suffix_of(reads[0]["rec"])
            msg = f"{fname} [{gname}] `{label}`: `{a}` and `{b}` share a row but their names do not pair: kept as separate signals"
            if difflib.SequenceMatcher(None, norm_pv(a), norm_pv(b)).ratio() >= 0.6:
                ctx.judgements.append(msg + " (similar names: possibly a screen bug)")
            else:
                ctx.notes.append(msg)
        if m is not None:
            reads.remove(m)
            ordered.remove(m)
            w["pair"] = m
        pairs.append(w)

    comps: list[dict] = []
    for d in ordered:
        rec = record_of(ctx, d["rec"])
        is_field = "." in d["rec"]
        suffix = suffix_of(d["rec"])
        base = re.sub(r"[:_]?RBV$", "", suffix)
        if is_field:
            # `$(P)$(M).VELO` must not take the name of a record `$(P)$(M):VELO`
            base = suffix if "." in suffix.lstrip(".") else f"Field {suffix}"
        if d["write"]:
            if "pair" in d:
                base = re.sub(r"[:_]?RBV$", "", suffix_of(d["pair"]["rec"]))
            if rec.rtype in INPUT and not is_field:
                ctx.judgements.append(
                    f"{fname}: `{d['rec']}` is an input record ({rec.rtype}) with a write widget"
                )
            acts = press.get(d["rec"], [])
            if len(acts) >= 2:
                name = unique_name(ctx, base, d["rec"])
                c = {
                    "type": "SignalW",
                    "name": name,
                    "write_pv": d["rec"],
                    "write_widget": {"type": "ButtonPanel", "actions": button_actions(acts + second.get(d["rec"], []), label or name)},
                }
                if "pair" in d:
                    c["type"] = "SignalRW"
                    c["read_pv"] = d["pair"]["rec"]
                    c["read_widget"] = widget_to_read(ctx, d["pair"]["rec"])
            elif len(acts) == 1 and "pair" not in d:
                # pvi turns a bare SignalX into a "Go" button that writes 1, so
                # a button with a value has to be a one-button panel.
                # a static caption names the button; a .DESC stand-in leaves the record's name
                # beside another record's value the row's text names that value, not this button
                beside = is_field and own_button_text(d["objs"][0], fname) and any(o is not d and o["read"] for o in ordered)
                bare = base if sum("." not in o["rec"] for o in ordered) > 1 or not label or d["caption"] or beside else label
                called = base if d.get("icon") else d["caption"] if d["static"] else bare
                name = unique_name(ctx, called, d["rec"])
                c = {
                    "type": "SignalW",
                    "name": name,
                    "write_pv": d["rec"],
                    "write_widget": {"type": "ButtonPanel", "actions": button_actions(acts + second.get(d["rec"], []), label or name)},
                }
                c["_bare_button"] = d.get("icon") or not re.search(r"[A-Za-z0-9]", acts[0][0])
            elif "pair" in d:
                c = {
                    "type": "SignalRW",
                    "name": unique_name(ctx, base, d["rec"]),
                    "write_pv": d["rec"],
                    "write_widget": write_widget(rec),
                    "read_pv": d["pair"]["rec"],
                    "read_widget": widget_to_read(ctx, d["pair"]["rec"]),
                }
            elif is_field and d["rec"].endswith(".PROC"):
                # a write to .PROC only processes the record, however the screen drew it
                c = {
                    "type": "SignalW",
                    "name": unique_name(ctx, base, d["rec"]),
                    "write_pv": d["rec"],
                    "write_widget": {"type": "ButtonPanel", "actions": {pascal(label or "Process"): "1"}},
                }
            elif is_field:
                c = {
                    "type": "SignalW",
                    "name": unique_name(ctx, base, d["rec"]),
                    "write_pv": d["rec"],
                    "write_widget": widget_to_write(ctx, d["rec"]),
                }
            elif rec.rtype in ("bo", "bi"):
                # a toggle shows its own state; the LED is how existing files show it
                c = {
                    "type": "SignalRW",
                    "name": unique_name(ctx, base, d["rec"]),
                    "write_pv": d["rec"],
                    "write_widget": write_widget(rec),
                    "read_pv": d["rec"],
                    "read_widget": read_widget(rec),
                }
            else:
                c = {
                    "type": "SignalW",
                    "name": unique_name(ctx, base, d["rec"]),
                    "write_pv": d["rec"],
                    "write_widget": write_widget(rec),
                }
        else:
            if rec.rtype in OUTPUT and not is_field:
                ctx.readonly.append(d["rec"])
            c = {
                "type": "SignalR",
                "name": unique_name(ctx, base, d["rec"]),
                "read_pv": d["rec"],
                "read_widget": widget_to_read(ctx, d["rec"], d["objs"]),
            }
        if d["caption"]:
            c["_caption"] = d["caption"]
        c["_x"] = d["x"]
        c["_read"] = d["read"]
        c["_objs"] = d["objs"] + (d.get("pair", {}).get("objs", []) if "pair" in d else [])
        comps.append(c)

    if not comps:
        return []
    plain = [c for c in comps if not c.get("_caption")]
    for c in comps:
        if c.get("_caption"):
            c["label"] = c["_caption"]
    if stacked(left) and len(plain) >= 2:
        share_column(left, plain)
    elif label and plain:
        plain[0]["label"] = label
        for c in plain:
            if c.get("_bare_button"):
                c["label"] = label
    return comps


def share_column(column: list[Obj], signals: list[dict]):
    """A column of labels beside several signals: each signal takes the nearest one."""
    free = sorted(column, key=lambda t: (t.y, t.x))
    for c in sorted(signals, key=lambda c: (min(o.cy for o in c["_objs"]), c["_x"])):
        if not free:
            break
        cy = min(o.cy for o in c["_objs"])
        near = min(free, key=lambda t: abs(t.cy - cy))
        if not junk_label(clean_label(text_of(near))):
            c["label"] = clean_label(text_of(near))
            c["_own_label"] = True
        free.remove(near)


def button_actions(acts: list[tuple[str, str]], fallback: str) -> dict:
    """pvi names a button by its action. A button with no text takes the row's, and two
    that would share a name are told apart by the value each writes."""
    # text with nothing to name a button by, such as an arrow, is no text
    named = [(pascal(shorten(a if re.search(r"[A-Za-z0-9]", a) else fallback, 40)), v) for a, v in acts]
    return tell_apart(named)


def tell_apart(named: list[tuple[str, str]]) -> dict:
    """Action name to value. Two names alike with different values each take their value."""
    clash = {n for n, v in named if len({w for m, w in named if m == n}) > 1}
    out: dict = {}
    for n, v in named:
        name = base = pascal(f"{n} {v}") if n in clash else n
        i = 2
        while name in out and out[name] != v:
            name = f"{base}V{i}"
            i += 1
        out[name] = v
    return out


def merge_actions(copies: list[dict]) -> dict:
    """The buttons of one PV as one panel, in the order given: each value once, under
    the first label it had."""
    named: list[tuple[str, str]] = []
    for acts in copies:
        named += [(n, v) for n, v in acts.items() if all(v != w for _, w in named)]
    return tell_apart(named)


def is_panel(c: dict) -> bool:
    return c.get("write_widget", {}).get("type") == "ButtonPanel"


def lift_panels(tree: list[dict]) -> list[dict]:
    """pvi asserts on a ButtonPanel in a Row, so a Row holding one gives its signals to
    the grid around it, where each shows on its own line."""
    out: list[dict] = []
    for c in tree:
        if c["type"] != "Group":
            out.append(c)
            continue
        c["children"] = lift_panels(c["children"])
        if c["layout"]["type"] == "Row" and any(is_panel(k) for k in c["children"]):
            if c.get("label") and c["label"] != c["children"][0]["name"]:
                c["children"][0].setdefault("label", c["label"])
            out.extend(c["children"])
        else:
            out.append(c)
    return out


def split_segments(row: Row) -> list[Row]:
    """`label widget label widget` on one line is two rows side by side."""
    elems = [(u.obj.x, "w", u) for u in row.uses if u.fieldname != "DESC"]
    elems += [(u.obj.x, "t", u) for u in row.uses if u.fieldname == "DESC" and not u.on_button]
    elems += [(t.x, "t", t) for t in row.texts]
    elems.sort(key=lambda e: e[0])
    segs: list[Row] = []
    cur = None
    prev = None
    for i, (_x, kind, v) in enumerate(elems):
        later_widget = any(e[1] == "w" for e in elems[i + 1 :])
        if cur is None or (kind == "t" and prev == "w" and later_widget):
            cur = Row(row.y1, row.y2, heading=row.heading)
            cur.header = None  # type: ignore[attr-defined]
            segs.append(cur)
        if kind == "w" or isinstance(v, Use):
            cur.uses.append(v)
        else:
            cur.texts.append(v)
        prev = kind
    if not segs:
        cur = Row(row.y1, row.y2)
        cur.header = None  # type: ignore[attr-defined]
        segs.append(cur)
    segs[0].header = getattr(row, "header", None)  # type: ignore[attr-defined]
    segs[0].links = row.links
    return segs


def build_group(ctx: Ctx, g: dict, fname: str, gname: str, placed: dict, device_stem: str) -> list[dict]:
    children: list[dict] = []
    # rows of `label widget label widget` read down each column in turn
    tagged = [(i, seg) for row in g["rows"] for i, seg in enumerate(split_segments(row))]
    rows = [seg for _, seg in sorted(tagged, key=lambda t: t[0])]
    for row in rows:
        comps = row_components(ctx, row, fname, gname, placed)
        lnk = sorted(row.links, key=lambda ln: ln["obj"].x)
        for ln in lnk:
            comps.extend(link_components(ctx, ln, fname, row, device_stem))
        if len(comps) >= 2:
            # several widgets on one row with one label is a pvi table row
            signal_comps = [c for c in comps if c["type"].startswith("Signal")]
            others = [c for c in comps if not c["type"].startswith("Signal")]
            # pvi expands a ButtonPanel only at grid level, never inside a Row
            panel = any(c.get("write_widget", {}).get("type") == "ButtonPanel" for c in signal_comps)
            # signals with a label each stay in the grid, where each one shows
            own = any(c.get("_own_label") for c in signal_comps)
            if len(signal_comps) >= 2 and not panel and not own:
                lab = signal_comps[0].pop("label", None) or None
                if not lab:
                    # a string record that holds the row name gives it a static label
                    first = signal_comps[0]
                    rec = ctx.records.get(first.get("read_pv", ""))
                    val = rec.fields.get("VAL", "") if rec else ""
                    lab = clean_label(default_of(val)) if rec and rec.rtype.startswith("string") and "$(" in val else ""
                    lab = lab or first["name"]
                head = getattr(row, "header", None)
                base = "Row" + signal_comps[0]["name"]
                grp = {
                    "type": "Group",
                    "name": unique_name(ctx, base, "row:" + base),
                    "layout": {"type": "Row"},
                    "children": signal_comps,
                }
                if lab:
                    grp["label"] = lab
                if head and len(head) == len(signal_comps):
                    grp["layout"]["header"] = [h or " " for h in head]
                children.append(grp)
                children.extend(others)
                continue
        children.extend(comps)
    return children


def link_components(ctx: Ctx, ln: dict, fname: str, row: Row, device_stem: str) -> list[dict]:
    target = data_path(ctx, ln["file"])
    tf = ln["file"] if ln["file"].endswith(".edl") else ln["file"] + ".edl"
    if tf in ctx.skip_links:
        ctx.external.append(f"{fname} -> {tf}: skipped by override")
        return []
    tf = ctx.subst.get(tf, tf)
    if tf in ctx.skip_links:
        ctx.external.append(f"{fname} -> {tf}: skipped by override")
        return []
    if target is None:
        ctx.external.append(f"{fname} -> {tf} ({ln['label'] or ln['kind']}): not in this release, not followed")
        return []
    # A display of another entity is a device of its own.
    if tf in ctx.roots and ctx.roots[tf] != device_stem and ln["kind"] == "related":
        stem = ctx.roots[tf]
        macros = {k: v for k, v in parse_symbols(ln["symbols"], ctx.env_cur).items()}
        if ctx.sweep:
            # the target's bob uses its database macros, the link its screen macros
            tag = ctx.root_macros.get(tf, {})
            renamed = {}
            for k, v in macros.items():
                names = macros_in(tag.get(k, ""))
                if names and tag.get(k) == "".join(f"$({n})" for n in names):
                    # `$(P)$(R)` is one value on the screen: the first takes it, the rest are empty
                    renamed[names[0]] = v
                    renamed.update({n: "" for n in names[1:] if n not in renamed})
                else:
                    renamed[k] = v
            macros = renamed
        label = clean_label(ln["label"]) or stem
        for v in macros.values():
            ctx.device_macros.update(macros_in(v))
        name = unique_name(ctx, label, "ref:" + stem + str(macros))
        pvp = next(iter(macros.values()), "") if macros else ""
        ctx.device_refs[name] = stem
        if ln.get("gates"):
            ctx.gated_refs.append(dict(screen=fname, device=stem, gates=ln["gates"]))
            ctx.judgements.append(f"{fname}: a gated link opens device {stem}: its button is always shown here, and that device's writes are not treated as gated")
        return [
            {
                "type": "DeviceRef",
                "name": name,
                "label": label,
                "pv": f"{pvp}:PVI",
                "ui": f"{stem}.pvi.bob",
                "macros": macros,
            }
        ]
    if tf in ctx.visiting:
        return []
    if ctx.sweep and len(ctx.visiting) >= 5:
        ctx.external.append(f"{fname} -> {tf}: nested too deep, not followed")
        return []
    # Does the target address this device's records?
    env2 = ln["env"]
    probe = parse_edl(target)
    hit = miss = 0
    n_pv = 0
    for o in probe.objects:
        for u in pv_uses(o):
            if u.role == "decor":
                continue
            n_pv += 1
            pv = expand(u.pv, env2)
            if resolve(ctx, pv)[0]:
                hit += 1
            else:
                miss += 1
    if hit == 0:
        ctx.external.append(f"{fname} -> {tf} ({ln['label'] or ln['kind']}): no PV of this device, not followed")
        return []
    ctx.screens.append(dict(file=tf, path=str(target), env=env2, label=ln["label"]))
    label = ctx.link_labels.get(tf) or literal_macros(clean_label(ln["label"]), ctx) or ln.get("caption", "")
    if junk_label(label):
        label = ""
    if not label:
        # what the link passes in names it, where it is a real value; its macros say nothing
        sym = parse_symbols(ln["symbols"], ctx.env_cur)
        label = " ".join(f"{k.title()} {v}" for k, v in sym.items() if "$(" not in v) or Path(tf).stem
    ctx.visiting.append(tf)
    gates_before = len(ctx.link_gates)
    ctx.link_gates.extend(ln.get("gates") or [])
    saved = ctx.env_cur
    ctx.env_cur = env2
    groups = layout_screen(ctx, target, env2)
    # A confirm dialog: one write and a status, shown inline where its button is.
    inner = sum(len(g["items"]) for g in groups)
    children: list[dict] = []
    warning = ""
    if inner <= 3 and ln["kind"] == "related":
        title_w = probe.w * 0.6
        texts = [clean_label(text_of(o)) for o in probe.objects if o.cls == "activeXTextClass" and o.w < probe.w * 2]
        warning = max((t for t in texts if len(t) > 20 and "$(" not in t), key=len, default="")
        if ctx.sweep and not warning:
            warning = next((t for t in texts if WARN_WORDS.search(t) and "$(" not in t), "")
    if inner <= 3 and ln["kind"] == "related" and not warning and not any(g["links"] for g in groups):
        comps = []
        for g in groups:
            for r in g["rows"]:
                r.texts = []
                comps.extend(row_components(ctx, r, tf, label, {}))
        for c in comps:
            c.setdefault("label", label)
        ctx.notes.append(f"{fname}: small dialog {tf} shown inline as `{label}`")
        for c in comps:
            if "write_pv" in c:
                ctx.dialogs.append(dict(kind="small_dialog_inlined", screen=fname, dialog=tf, text="", pv=c["write_pv"],
                                        handled=f"no warning text: shown inline as `{label}`"))
        ctx.visiting.pop()
        del ctx.link_gates[gates_before:]
        ctx.env_cur = saved
        return comps
    children = screen_children(ctx, groups, tf, device_stem, nested=True)
    ctx.visiting.pop()
    del ctx.link_gates[gates_before:]
    ctx.env_cur = saved
    if not children:
        return []
    if warning:
        # keep the two clicks of a confirmation; its text becomes the row label
        def mark(tree):
            for c in tree:
                if c["type"] == "Group" and c["layout"]["type"] == "Grid":
                    mark(c["children"])
                else:
                    c["label"] = warning
                    c["_warning"] = True  # a safety text: never shortened
                    if c["type"] == "Group":
                        for k in c["children"]:
                            k["_guarded"] = True
                    else:
                        c["_guarded"] = True

        mark(children)
        ctx.judgements.append(
            f"{fname}: confirmation dialog {tf} kept as sub-screen `{label}`, its text on the row label: \"{warning}\""
        )
        guarded = [c["write_pv"] for c in walk_signals(children) if "write_pv" in c]
        ctx.dialogs.append(dict(kind="confirmation_dialog", screen=fname, dialog=tf, text=warning,
                                pv=", ".join(guarded), handled=f"kept as sub-screen `{label}`"))
    name = unique_name(ctx, label, "sub:" + tf + label + ln["symbols"])
    return [
        {
            "type": "Group",
            "name": name,
            "label": label,
            "layout": {"type": "SubScreen", "labelled": False},
            "children": children,
        }
    ]


def screen_children(ctx: Ctx, groups: list[dict], fname: str, device_stem: str, nested=False) -> list[dict]:
    children: list[dict] = []
    for g in groups:
        title = g["title"]
        if not title:
            title = ctx.group_names.get(f"{fname}:{g['key']}") or (
                "General" if g["key"] == "__top__" else "Details"
            )
            if g["key"] != "__top__":
                ctx.judgements.append(f"{fname}: frame with no heading named `{title}`")
        inner = build_group(ctx, g, fname, title, {}, device_stem)
        if not inner:
            continue
        if g["key"] == "__top__" and all(
            c["type"] == "DeviceRef" or (c["type"] == "Group" and c["layout"]["type"] == "SubScreen")
            for c in inner
        ):
            # buttons alone, outside any frame, stay at the top of the screen
            children.extend(inner)
            continue
        name = unique_name(ctx, title, f"group:{fname}:{g['key']}")
        children.append(
            {
                "type": "Group",
                "name": name,
                **({"label": title} if title != name else {}),
                "layout": {"type": "Grid", "labelled": True},
                "children": inner,
            }
        )
    return children


def walk_signals(tree):
    for c in tree:
        if c["type"] == "Group":
            yield from walk_signals(c["children"])
        else:
            yield c


def dedupe(children: list[dict], ctx: Ctx):
    """A record shown twice: the read/write form wins over a plain read. Buttons on one
    PV become one panel wherever the screens draw them, on the copy that is kept."""
    rw_reads = set()
    w_seen = set()
    rw_writes = set()
    for c in walk_signals(children):
        if c["type"] in ("SignalRW", "SignalW", "SignalX"):
            if c.get("read_pv"):
                rw_reads.add(c["read_pv"])
            w_seen.add(c["write_pv"])
        if c["type"] == "SignalRW":
            rw_writes.add(c["write_pv"])
    # a write behind a confirmation dialog must not also be one click away
    guarded = {c["write_pv"] for c in walk_signals(children) if c.get("_guarded") and "write_pv" in c}
    seen: set = set()
    panels: dict[str, list[dict]] = {}
    for c in walk_signals(children):
        if is_panel(c):
            panels.setdefault(c["write_pv"], []).append(c["write_widget"]["actions"])

    def scrub(tree):
        out = []
        for c in tree:
            if c["type"] == "Group":
                before = len(c["children"])
                c["children"] = scrub(c["children"])
                if len(c["children"]) != before and c["layout"].get("header"):
                    c["layout"].pop("header")  # its columns no longer line up
                if c["children"]:
                    out.append(c)
                continue
            if "write_pv" in c and c["write_pv"] in guarded and not c.get("_guarded"):
                ctx.judgements.append(f"`{c['write_pv']}` has a confirmation dialog: only the dialog's copy kept")
                continue
            if c["type"] == "SignalR":
                pv = c["read_pv"]
                if pv in rw_reads or pv in w_seen:
                    ctx.dropped_reads.add(pv)
                    ctx.notes.append(f"`{pv}` is shown twice: kept in its read/write row")
                    continue
                if pv in seen:
                    ctx.notes.append(f"`{pv}` is shown twice: kept the first")
                    continue
                seen.add(pv)
            elif c["type"] in ("SignalRW", "SignalW", "SignalX"):
                if c["type"] == "SignalW" and c["write_pv"] in rw_writes:
                    ctx.notes.append(f"`{c['write_pv']}` is shown twice: kept in its read/write row")
                    continue
                key = (c["write_pv"], c.get("read_pv"), c["type"])
                if key in seen:
                    ctx.notes.append(f"`{c['write_pv']}` is shown twice: kept the first")
                    continue
                seen.add(key)
            elif c["type"] == "DeviceRef":
                key = ("ref", c["ui"], str(c["macros"]))
                if key in seen:
                    continue
                seen.add(key)
            out.append(c)
        return out

    kept = scrub(children)
    for c in walk_signals(kept):
        pv = c.get("write_pv")
        if pv not in panels:
            continue
        values = {v for acts in panels[pv] for v in acts.values()}
        if not is_panel(c):
            why = f"writable through its {c['write_widget']['type']}"
            ctx.buttons_covered[pv] = dict(values=sorted(values), why=why)
            ctx.notes.append(f"`{pv}`: buttons writing {sorted(values)} left out: {why}")
        elif len(panels[pv]) > 1:
            first_values = set(panels[pv][0].values())
            c["write_widget"]["actions"] = merge_actions(panels[pv])
            if values - first_values:
                ctx.merged_buttons[pv] = c["write_widget"]["actions"]
                ctx.notes.append(f"`{pv}`: {len(values)} buttons with different values merged into one panel")
        if is_panel(c) and pv in ctx.momentary:
            c["write_widget"]["actions"] = fullest_actions(c["write_widget"]["actions"], ctx.momentary[pv], pv)
    return lift_panels(kept)


def fullest_actions(actions: dict, labels: list[str], pv: str) -> dict:
    """Screens name one held button `Forward` and `Jog Forward`. Out of the row that
    explains the short name, the actions take the name that says it all."""
    short = labels[0]
    full = max((x for x in labels if short.lower() in x.lower()), key=len)
    names = {pascal(short): pascal(full), pascal(release_text(short, pv)): pascal(release_text(full, pv))}
    return {names.get(n, n): v for n, v in actions.items()}


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def clean(c):
    if isinstance(c, dict):
        out = {}
        order = ["type", "name", "label", "layout", "write_pv", "write_widget", "read_pv", "read_widget", "value", "pv", "ui", "macros", "children"]
        for k in order:
            if k in c:
                out[k] = clean(c[k])
        for k, v in c.items():
            if k not in out and not k.startswith("_"):
                out[k] = clean(v)
        return out
    if isinstance(c, list):
        return [clean(x) for x in c]
    return c


def macros_of_device(children: list[dict]) -> set[str]:
    out: set[str] = set()
    for c in walk_signals(children):
        for k in ("read_pv", "write_pv"):
            if k in c:
                out.update(macros_in(c[k]))
        if c["type"] == "DeviceRef":
            for v in c["macros"].values():
                out.update(macros_in(v))
    return out


def entity_block(text: str, entity: str) -> tuple[int, int]:
    """Line span of an entity in a support yaml, found textually."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        m = re.match(r"^  - name:\s*(?:&\S+\s+)?(\S+)\s*$", ln)
        if m and m.group(1) == entity:
            start = i
            continue
        if start is not None and re.match(r"^  - name:", ln):
            return start, i
        if start is not None and re.match(r"^\S", ln):
            return start, i
    if start is None:
        raise KeyError(entity)
    return start, len(lines)


def insert_pvi(text: str, entity: str, block: str) -> str:
    s, e = entity_block(text, entity)
    lines = text.splitlines()
    body = lines[s:e]
    if any(re.match(r"^    pvi:", ln) for ln in body):
        # replace an existing section written by a previous run
        i = next(j for j, ln in enumerate(body) if re.match(r"^    pvi:", ln))
        j = i + 1
        while j < len(body) and (body[j].startswith("      ") or (not body[j].strip() and j + 1 < len(body) and body[j + 1].startswith("      "))):
            j += 1
        new = body[:i] + block.splitlines() + body[j:]
    else:
        k = len(body)
        while k > 0 and not body[k - 1].strip():
            k -= 1
        new = body[:k] + [""] + block.splitlines() + body[k:]
    return "\n".join(lines[:s] + new + lines[e:]) + "\n"


def head_text(repo: Path, rel: str) -> str:
    """The committed support yaml: generation starts from it on every run."""
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"HEAD:{rel}"],
        capture_output=True, text=True, check=True,
    ).stdout


def pvi_block(yaml_path: str, ui_macros: dict, pv_prefix: str) -> str:
    """The `pvi:` section: a screen and no PVI PV, which only scanned devices need."""
    out = ["    pvi:", f"      yaml_path: {yaml_path}", "      ui_macros:" + ("" if ui_macros else " {}")]
    for k, v in ui_macros.items():
        out.append(f"        {k}:" + (f" {json.dumps(str(v))}" if v is not None else ""))
    out.append(f'      pv_prefix: "{pv_prefix}"')
    return "\n".join(out)


def tail_of(s: str) -> str:
    """Text after a name's last macro."""
    return s[s.rindex(")") + 1 :] if "$(" in s else s


def screen_files(release: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    for f in sorted(release.glob("data/*.edl")) + sorted(release.glob("*App/opi/edl/*.edl")):
        seen.setdefault(f.name, f)
    return list(seen.values())


def screen_pvs(path: Path) -> list[str]:
    """The distinct records a screen shows or writes, fields removed."""
    out: list[str] = []
    for o in parse_edl(path).objects:
        for u in pv_uses(o):
            if u.role != "decor":
                base = u.pv.partition(".")[0]
                if base and base not in out:
                    out.append(base)
    return out


def infer_env(pvs: list[str], records) -> dict[str, str]:
    """Screen macro -> value in db macro space, by majority over matching names."""
    by_tail: dict[str, list[str]] = {}
    for r in records:
        by_tail.setdefault(tail_of(r), []).append(r)
    votes: dict[str, dict[str, int]] = {}

    def vote(m: str, v: str):
        votes.setdefault(m, {})
        votes[m][v] = votes[m].get(v, 0) + 1

    for pv in pvs:
        names = macros_in(pv)
        if not names:
            continue
        if pv in records:
            for m in names:
                vote(m, f"$({m})")
            continue
        t = tail_of(pv)
        if not t:
            continue
        seen: set[str] = set()
        rx = ""
        for part in re.split(r"(\$\(\w+\))", pv):
            mm = re.fullmatch(r"\$\((\w+)\)", part)
            if not mm:
                rx += re.escape(part)
            elif mm.group(1) in seen:
                rx += f"(?P={mm.group(1)})"
            else:
                seen.add(mm.group(1))
                rx += f"(?P<{mm.group(1)}>.*?)"
        try:
            pat = re.compile(rx)
        except re.error:
            continue
        for r in by_tail.get(t, []):
            if hit := pat.fullmatch(r):
                for k, v in hit.groupdict().items():
                    vote(k, v)
    return {m: max(c, key=lambda v: (c[v], len(v))) for m, c in votes.items()}


def score_screen(path: Path, records, stem: str) -> dict | None:
    pvs = screen_pvs(path)
    if not pvs:
        return None
    env = infer_env(pvs, records)
    hits = set()
    for pv in pvs:
        full = expand(pv, env)
        rec = full if full in records else match_tail(full, records)
        if rec:
            hits.add(rec)
    if not hits:
        return None
    precision = len(hits) / len(pvs)
    name = path.stem.lower()
    near = stem.lower() in name or name in stem.lower()
    return dict(path=path, env=env, hits=hits, precision=precision, near=near)


def good_enough(sc: dict, n_records: int) -> bool:
    if len(sc["hits"]) >= 2 and sc["precision"] >= 0.4:
        return True
    return n_records <= 3 and sc["precision"] >= 0.6


def search_screens(release: Path, records, stem: str) -> list[dict]:
    """Screens of the release that address this database, best first."""
    out = []
    for f in screen_files(release):
        sc = score_screen(f, records, stem)
        if sc and good_enough(sc, len(records)):
            out.append(sc)
    out.sort(key=lambda s: (-len(s["hits"]) * s["precision"], not s["near"], s["path"].name))
    return out


def hits_of(path: Path, env: dict, records) -> set[str]:
    return {expand(pv, env) for pv in screen_pvs(path)} & set(records)


def tag_env(tag: dict, release: Path, edl: str, records) -> dict:
    """A tag's macros, completed from the record names; replaced if they place nothing."""
    f = edl if edl.endswith(".edl") else edl + ".edl"
    probe = Ctx(module="", release=release, dbs=[], records={}, env={}, roots={}, subst={}, sweep=True)
    p = data_path(probe, f)
    if p is None:
        return tag
    pvs = screen_pvs(p)
    inferred = infer_env(pvs, records)
    merged = {**inferred, **tag}
    if not ({expand(pv, merged) for pv in pvs} & set(records)) and ({expand(pv, inferred) for pv in pvs} & set(records)):
        return inferred
    return merged


def recs_of(release: Path, files: list[str], extra: list[Path]):
    return load_records(release, files, extra, True)[1]


def conditional(d: dict) -> bool:
    e = d.get("enabled")
    return e is not None and str(e).lower() not in ("true", "yes", "1")


def load_records(release: Path, files: list[str], extra: list[Path], sweep: bool):
    records: dict = {}
    dbs = []
    for f in files:
        fp = find_db(release, f, extra) if sweep else release / "db" / f.rsplit("/", 1)[-1]
        if fp is not None and fp.exists():
            db = parse_db(fp, search=db_search_path(release, extra)) if sweep else parse_db(fp)
            dbs.append(db)
            records.update(db.records)
    return dbs, records


def process(module: str, write: bool, ov: dict | None = None, out_root: Path | None = None):
    ov = ov or yaml.safe_load((CFG.overrides / f"{module}.yaml").read_text())
    sweep = bool(ov.get("sweep"))
    repo = CFG.repos[ov["repo"]]
    release = Path(ov["release"])
    folder = ov.get("dir", module)
    yaml_name = ov.get("yaml", f"{module}.ibek.support.yaml")
    sup_rel = f"{folder}/{yaml_name}"
    sup_path = repo / sup_rel
    head = head_text(repo, sup_rel)
    sup = yaml.safe_load(head)
    outdir = (out_root or CFG.output) / module
    if sweep and outdir.exists():
        for old in outdir.glob("*.pvi.device.yaml"):
            old.unlink()
    outdir.mkdir(parents=True, exist_ok=True)
    reserved = set(ov.get("reserved_stems", []))
    extra_db = [repo / folder]

    def file_stem(stem: str) -> str:
        if stem in reserved or not stem[:1].isalpha():
            return re.sub(r"\W", "", module) + "_" + stem
        return stem

    # entity -> template -> screen
    plan = []
    roots: dict[str, str] = {}
    root_macros: dict[str, dict] = {}
    models_no_screen = []
    for em in sup.get("entity_models") or []:
        name = em["name"]
        if name in ov.get("skip_entities", {}):
            models_no_screen.append((name, ov["skip_entities"][name]))
            continue
        files = []
        notes = []
        for d in em.get("databases") or []:
            if "file" not in d:
                continue
            f = d["file"].strip()
            if sweep and "{{" in f:
                notes.append(f"database `{f}` has a computed file name: its records are not used")
                continue
            if sweep and conditional(d):
                notes.append(f"database `{f}` loads conditionally ({d['enabled']}): its records are not used")
                continue
            files.append(f)
        chosen = None
        eo = ov.get("entities", {}).get(name, {})
        extras: list[dict] = []
        for f in files:
            stem = f.rsplit("/", 1)[-1]
            p = (find_db(release, f, extra_db) if sweep else release / "db" / stem)
            if p is None or not p.exists():
                continue
            db = parse_db(p, search=db_search_path(release, extra_db)) if sweep else parse_db(p)
            edl = None
            tags = db.gui
            if sweep:
                # a tag naming a screen this release cannot supply says nothing
                probe = Ctx(module=module, release=release, dbs=[], records={}, env={}, roots={}, subst={}, sweep=True)
                tags = [t for t in db.gui + db.gui_embed if "$(" not in t[0] and data_path(probe, t[0])]
                # tags of included templates come too: the screen showing most records leads
                recs_here = recs_of(release, files, extra_db)
                tags.sort(key=lambda t: -len(hits_of(data_path(probe, t[0]), {**infer_env(screen_pvs(data_path(probe, t[0])), recs_here), **t[1]}, recs_here)))
                for t in tags[1:]:
                    extras.append(dict(file=t[0] if t[0].endswith(".edl") else t[0] + ".edl", macros=t[1]))
            if tags:
                edl, macros = tags[0]
                how = "gui tag"
                if sweep:
                    macros = tag_env(macros, release, edl, recs_of(release, files, extra_db))
            elif (release / "data" / (Path(stem).stem + ".edl")).exists():
                edl = Path(stem).stem + ".edl"
                macros = {m: f"$({m})" for r in db.records for m in macros_in(r)}
                if sweep:
                    macros.update(infer_env(screen_pvs(release / "data" / edl), db.records))
                how = "same name as template"
            if eo.get("screen"):
                edl = eo["screen"]
                macros = eo.get("macros", {})
                how = "override"
            if edl:
                edl = edl if edl.endswith(".edl") or not sweep else edl + ".edl"
                if chosen is None:
                    chosen = (stem, edl, macros, how)
                elif sweep and edl != chosen[1]:
                    extras.append(dict(file=edl, macros=macros))
        search_rest: list[dict] = []
        if chosen is None and sweep:
            # no tag and no same-named screen: find the screens showing its records
            _, recs = load_records(release, files, extra_db, True)
            found = search_screens(release, recs, name) if recs else []
            if found:
                best = found[0]
                first = next((f for f in files if find_db(release, f, extra_db)), files[0])
                chosen = (first.rsplit("/", 1)[-1], best["path"].name, best["env"], "screen search")
                search_rest = found[1:]
        if not chosen:
            why = "no database with an EDM screen"
            if not files:
                why = "no database"
            elif sweep and not any(find_db(release, f, extra_db) for f in files):
                why = f"database not in release: {files[0]}"
            elif sweep and screen_files(release):
                why = "screens exist in the release, none addresses its records"
            models_no_screen.append((name, why))
            continue
        plan.append(dict(entity=em, files=files, stem=Path(chosen[0]).stem, tmpl=chosen[0], edl=chosen[1],
                         macros=chosen[2], how=chosen[3], extras=extras, search_rest=search_rest, notes=notes))
        roots.setdefault(chosen[1], file_stem(Path(chosen[0]).stem))
        root_macros.setdefault(chosen[1], chosen[2])

    report = dict(module=module, repo=ov["repo"], folder=folder, release=str(release), devices={}, no_screen=models_no_screen,
                  release_note=ov.get("release_note", ""), yaml=yaml_name, entity_failures={})
    done = {}
    for p in plan:
        em = p["entity"]
        stem = p["stem"]
        if stem in done:
            p["device"] = done[stem]
            continue
        try:
            build_device(p, ov, module, release, extra_db, roots, root_macros, report, outdir, write, repo, folder, file_stem, sweep)
            dev0 = report["devices"][stem]
            weak = "error" in dev0 or dev0["n_placed"] < 0.1 * dev0["n_records"]
            if sweep and weak and p["how"] != "screen search":
                recs = recs_of(release, p["files"], extra_db)
                found = search_screens(release, recs, em["name"]) if recs else []
                if found and ("error" in dev0 or len(found[0]["hits"]) > dev0["n_placed"]):
                    first_error = dev0.get("error") or f"{p['edl']} placed {dev0['n_placed']} of {dev0['n_records']} records"
                    report["devices"].pop(stem)
                    p.update(edl=found[0]["path"].name, macros=found[0]["env"], how="screen search", search_rest=found[1:], extras=[])
                    p["notes"].append(f"{first_error}: root screen found by search instead")
                    roots.setdefault(p["edl"], file_stem(stem))
                    build_device(p, ov, module, release, extra_db, roots, root_macros, report, outdir, write, repo, folder, file_stem, sweep)
            if "error" not in report["devices"][stem]:
                done[stem] = stem
                p["device"] = stem
        except TimeoutError:
            raise  # the whole module's, and says nothing about this entity
        except Exception as e:  # noqa: BLE001
            if not sweep:
                raise
            report["devices"][stem] = dict(entity=em["name"], error=f"{type(e).__name__}: {e}")

    # write entity pvi sections
    new = head
    for p in plan:
        stem = p.get("device")
        if not stem or "error" in report["devices"].get(stem, {}):
            continue
        em = p["entity"]
        dev = report["devices"][stem]
        dbargs = {}
        for d in em.get("databases") or []:
            dbargs.update(d.get("args") or {})
        # the screen's own database decides, where databases disagree
        for d in em.get("databases") or []:
            if d.get("file", "").rsplit("/", 1)[-1] == p["tmpl"]:
                dbargs.update(d.get("args") or {})
        params = em.get("parameters") or {}
        ui = {}
        problems = []
        for m in dev["device_macros"]:
            if m in dbargs and dbargs[m] is not None:
                ui[m] = dbargs[m]
            elif m in params or m in dbargs:
                ui[m] = None
            elif sweep and any(("*" in k or "?" in k) and re.match(k, m) for k in dbargs) and m in params:
                ui[m] = None
            elif sweep and m in dev.get("macro_defaults", {}):
                ui[m] = dev["macro_defaults"][m]
                dev["notes"].append(f"macro `{m}` is set by no entity: its database default `{ui[m]}` used")
            else:
                problems.append(m)
        prefix = (macro_prefix if sweep else pv_prefix)(dev["placed"])
        dev.setdefault("entities", []).append(dict(name=em["name"], ui_macros=ui, pv_prefix=prefix, unmapped_macros=problems))
        if problems and sweep:
            report["entity_failures"][em["name"]] = f"macro not supplied by the entity: {', '.join(problems)}"
            continue
        try:
            block = pvi_block(f"{dev.get('file_stem', stem)}.pvi.device.yaml", ui, prefix)
            new = insert_pvi(new, em["name"], block)
        except KeyError:
            if not sweep:
                raise
            report["entity_failures"][em["name"]] = "entity block not found in the yaml text"
    (outdir / sup_path.name).write_text(new)
    if write:
        sup_path.write_text(new)
    (outdir / "report.json").write_text(json.dumps(report, indent=1, default=str))
    return report


def build_device(p, ov, module, release, extra_db, roots, root_macros, report, outdir, write, repo, folder, file_stem, sweep):
    em = p["entity"]
    stem = p["stem"]
    dbs, records = load_records(release, p["files"], extra_db, sweep)
    env = dict(p["macros"])
    dev_ov = ov.get("devices", {}).get(stem, {})
    ctx = Ctx(module=module, release=release, dbs=dbs, records=records, env=env, roots=roots,
              subst={**ov.get("subst", {}), **dev_ov.get("subst", {})}, sweep=sweep, root_macros=root_macros)
    ctx.link_labels = {**ov.get("link_labels", {}), **dev_ov.get("link_labels", {})}
    ctx.no_field_records = ov.get("no_field_records", {})
    ctx.notes.extend(p["notes"])
    for j in dev_ov.get("judgements", []) + ov.get("judgements", []):
        ctx.judgements.append(j)
    ctx.env_cur = env
    ctx.group_names = ov.get("group_names", {})
    ctx.skip_links = set(ov.get("skip_links", [])) | set(dev_ov.get("skip_links", []))
    rootpath = data_path(ctx, p["edl"])
    if rootpath is None:
        report["devices"][stem] = dict(entity=em["name"], error=f"root screen {p['edl']} not found")
        return
    if sweep and not parse_edl(rootpath).format_ok:
        report["devices"][stem] = dict(entity=em["name"], error=f"root screen {p['edl']} is not in the keyword EDL format")
        return
    device_id = file_stem(stem)
    ctx.screens.append(dict(file=p["edl"], path=str(rootpath), env=env, label="root"))
    ctx.visiting.append(p["edl"])
    groups = layout_screen(ctx, rootpath, env)
    children = screen_children(ctx, groups, p["edl"], device_id)

    def add_sub(file: str, label: str, sub_env: dict, why: str):
        ep = data_path(ctx, file)
        if ep is None or not parse_edl(ep).format_ok or file in ctx.visiting:
            return
        before = {c.get(k) for c in walk_signals(children) for k in ("read_pv", "write_pv") if k in c}
        ctx.visiting.append(file)
        saved = ctx.env_cur
        ctx.env_cur = sub_env
        sub = screen_children(ctx, layout_screen(ctx, ep, sub_env), file, device_id, nested=True)
        ctx.env_cur = saved
        ctx.visiting.pop()
        after = {c.get(k) for c in walk_signals(sub) for k in ("read_pv", "write_pv") if k in c}
        if not sub or (sweep and not (after - before)):
            return
        ctx.judgements.append(why)
        ctx.screens.append(dict(file=file, path=str(ep), env=sub_env, label=label))
        children.append(
            {
                "type": "Group",
                "name": unique_name(ctx, label, "extra:" + file),
                "label": label,
                "layout": {"type": "SubScreen", "labelled": False},
                "children": sub,
            }
        )

    # screens of the same template not reached from the root
    for ex in dev_ov.get("extra_screens", []):
        add_sub(ex["file"], ex["label"], env,
                f"{ex['file']} is not reachable from {p['edl']} but shows PVs of this template: added as sub-screen `{ex['label']}`")
    if sweep:
        placed_now = lambda: {c.get(k) for c in walk_signals(children) for k in ("read_pv", "write_pv") if k in c}  # noqa: E731
        for ex in p["extras"]:
            if ex["file"] not in {s["file"] for s in ctx.screens}:
                add_sub(ex["file"], Path(ex["file"]).stem, ex["macros"] or env,
                        f"{ex['file']} is another screen tagged in this entity's templates: added as a sub-screen")
        added = 0
        for sc in p["search_rest"]:
            if added >= 4:
                break
            new = sc["hits"] - placed_now()
            if len(new) >= 3 and sc["path"].name not in {s["file"] for s in ctx.screens}:
                add_sub(sc["path"].name, sc["path"].stem, sc["env"],
                        f"{sc['path'].name} found by search, shows {len(new)} more records: added as a sub-screen")
                added += 1
    children = dedupe(children, ctx)
    children = tidy_names(children)
    children = promote_only_screen(children, ctx)
    children, protected, unlisted = protect_writes(children, ctx, ov, module, em["name"])
    if sweep:
        tidy_labels(children, env, macros_of_device(children))
    finish_labels(children)
    device = {"label": ov.get("labels", {}).get(stem, device_id), "children": clean(children)}
    placed = set()
    for c in walk_signals(device["children"]):
        for k in ("read_pv", "write_pv"):
            if k in c:
                placed.add(c[k])
    if sweep and not placed:
        report["devices"][stem] = dict(entity=em["name"], error=f"no record of {p['tmpl']} is placed by {p['edl']}",
                                       on_screen_not_in_db={k: sorted(v) for k, v in ctx.unmatched.items()})
        return
    yaml_txt = (
        "# yaml-language-server: $schema=https://github.com/epics-containers/pvi/releases/latest/download/pvi.device.schema.json\n"
        f"# Grouped from the DLS EDM screen {p['edl']} ({module} {release.name}).\n"
        f"{REGEN_NOTE}\n\n"
        + yaml.dump(device, Dumper=Dumper, sort_keys=False, width=200, default_flow_style=False)
    )
    fname = f"{device_id}.pvi.device.yaml"
    (outdir / fname).write_text(yaml_txt)
    if write:
        (repo / folder / fname).write_text(yaml_txt)
    placed_records = {pv.partition(".")[0] for pv in placed}
    field_pvs = sorted(pv for pv in placed if "." in pv)
    missing_from_db = sorted(pv for pv in placed_records if pv not in records)
    left_out = sorted(r for r in records if r not in placed_records)
    defaults = {}
    for db in dbs:
        defaults.update(db.defaults)
    guarded = set()
    for d in ctx.dialogs:
        if d["kind"] == "confirmation_dialog":
            guarded.update(x.strip() for x in d["pv"].split(",") if x.strip())
    for g in ctx.gated:
        if not g["in_db"]:
            g["handled"] = "record not in the database: left out"
        elif g["pv"] in protected:
            g["handled"] = f"moved to {SUB_LABEL} ({protected[g['pv']]})"
        elif g["pv"] in guarded:
            g["handled"] = "included behind its confirmation sub-screen"
        elif g["pv"] in placed:
            g["handled"] = "included in its normal place, always visible"
        elif g["field"] and g["field"] != "VAL" and g["pv"] in ctx.fields_left:
            g["handled"] = f"field left out: {ctx.fields_left[g['pv']]}"
        else:
            g["handled"] = "not placed"
    for d in ctx.dialogs:
        if d["kind"] == "confirmation_dialog" and all(x.strip() in protected for x in d["pv"].split(",")):
            d["handled"] = f"moved to {SUB_LABEL}, its text on the row label"
    report["devices"][stem] = dict(
        entity=em["name"],
        file_stem=device_id,
        template=p["tmpl"],
        screen=p["edl"],
        how=p["how"],
        macros=p["macros"],
        n_records=len(records),
        n_placed=len(placed_records),
        placed=sorted(placed_records),
        field_pvs=field_pvs,
        fields_left=dict(ctx.fields_left),
        left_out=[(r, records[r].rtype, "decor-only" if r in ctx.decor else "") for r in left_out],
        on_screen_not_in_db={k: sorted(v) for k, v in ctx.unmatched.items()},
        pv_not_in_db=missing_from_db,
        external=sorted(set(ctx.external)),
        notes=sorted(set(ctx.notes)),
        judgements=sorted(set(ctx.judgements)),
        readonly_outputs=sorted(set(ctx.readonly) & placed),
        screens=[dict(file=s["file"], path=s["path"], env=s["env"], label=s["label"]) for s in ctx.screens],
        device_macros=sorted(macros_of_device(device["children"])),
        macro_defaults={k: v for k, v in defaults.items()},
        gated=ctx.gated,
        gated_refs=ctx.gated_refs,
        dialogs=ctx.dialogs,
        device_refs=dict(ctx.device_refs),
        protected=protected,
        protected_unlisted=unlisted,
        merged_buttons=ctx.merged_buttons,
        momentary=sorted(ctx.momentary),
        buttons_covered=ctx.buttons_covered,
    )


def protect_writes(children: list[dict], ctx: Ctx, ov: dict, module: str, entity: str):
    """Dangerous and unsure gated writes to the device's protected sub-screen."""
    classes = load_classes(Path(ov["protected_file"])) if ov.get("protected_file") else load_classes()
    # a momentary write goes to the sub-screen even from behind a confirmation dialog
    held = {k[2] for k, e in classes.items() if k[:2] == (module, entity) and e["class"] == "momentary"}
    # so does one behind a gated link: the screen asked for the gate and the dialog, and this keeps the friction of both
    for g in ctx.gated:
        entry = classes.get((module, entity, g["pv"]))
        if g.get("via_link") and (entry is None or entry["class"] in MOVED):
            held.add(g["pv"])
    for c in walk_signals(children):
        if c.get("write_pv") in held:
            if c.pop("_guarded", None) and c.get("_warning"):
                # out of the sub-screen that said what the question was about
                c["label"] = f"{c['label']} ({re.split(r'[.:]', c['write_pv'])[-1]})"
    targets, unlisted = targets_of(children, ctx.gated, classes, module, entity)
    if unlisted:
        ctx.judgements.append(f"{len(unlisted)} gated writes are not in the classification file, so count as unsure: {', '.join(unlisted[:5])}")
    after = children
    if targets:
        before = copy.deepcopy(children)
        after = move(children, targets, lambda pv: widget_to_read(ctx, pv), ctx.dropped_reads, lambda base, key: unique_name(ctx, base, key))
        if problems := verify_move(before, after, targets):
            raise ValueError(f"{entity}: protected move changed more than it should: {'; '.join(problems)}")
        ctx.judgements.append(f"{len(targets)} gated writes moved to `{SUB_LABEL}`, per the classification file")
    stops = {k[2] for k, e in classes.items() if k[:2] == (module, entity) and e["class"] == "keep-on-main"}
    after, pulled = on_main(after, stops, lambda base, key: unique_name(ctx, base, key))
    if pulled:
        ctx.judgements.append(f"{', '.join(pulled)} brought to the first screen, per the classification file")
    return after, targets, unlisted


def promote_only_screen(children: list[dict], ctx: Ctx) -> list[dict]:
    """A device entirely inside one sub-screen has that screen as its main screen,
    unless the sub-screen is a confirmation that must stay one click away."""
    if len(children) != 1 or children[0]["type"] != "Group" or children[0]["layout"]["type"] != "SubScreen":
        return children
    only = children[0]
    if any(c.get("_guarded") for c in walk_signals(only["children"])):
        return children
    ctx.judgements.append(f"the device is entirely inside sub-screen `{only.get('label', only['name'])}`: its contents are on the main screen")
    return only["children"]


def finish_labels(tree: list[dict]):
    """Last word on every label: junk macro labels go, so the name shows; long ones are cut."""
    for c in tree:
        if c.get("label"):
            if junk_label(c["label"]):
                del c["label"]
            elif not c.get("_warning"):
                c["label"] = shorten(c["label"])
        if c["type"] == "Group":
            finish_labels(c["children"])


def tidy_labels(tree: list[dict], env: dict, known: set[str]):
    """A label's macro is only filled in if the screen opens with it; otherwise its name stands."""
    for c in tree:
        if c.get("label") and "$(" in c["label"]:
            text = expand(c["label"], {k: v for k, v in env.items() if "$(" in v and not (set(macros_in(v)) - known)})
            c["label"] = clean_label(re.sub(r"\$\((\w+)\)", lambda m: m.group(0) if m.group(1) in known else m.group(1), text)) or c["name"]
        if c["type"] == "Group":
            tidy_labels(c["children"], env, known)


def tidy_names(children: list[dict]) -> list[dict]:
    """Free a numbered name when its unnumbered form was dropped by dedupe."""
    used = set()

    def collect(tree):
        for c in tree:
            used.add(c["name"])
            if c["type"] == "Group":
                collect(c["children"])

    collect(children)

    def fix(tree):
        for c in tree:
            m = re.fullmatch(r"(.*?[a-z])2", c["name"])
            # a number that belongs to the label (Loop 2) is the real name
            if c["type"] == "Group" and m and m.group(1) not in used and pascal(c.get("label", m.group(1))) == m.group(1):
                used.add(m.group(1))
                c["name"] = m.group(1)
            if c["type"] == "Group":
                fix(c["children"])

    fix(children)
    return children


WARN_WORDS = re.compile(r"\b(sure|confirm|warning|caution|danger|trip)\b", re.I)


def pv_prefix(placed: list[str]) -> str:
    """Longest common macro-and-text prefix ending at a separator."""
    if not placed:
        return ""
    a = min(placed)
    b = max(placed)
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    p = a[:i]
    # back off to just after the last separator, never inside a macro
    m = re.match(r"^(.*[:\-_)])", p)
    p = m.group(1) if m else ""
    while p.count("$(") != p.count(")"):
        p = p[:-1]
    return p


def macro_prefix(placed: list[str]) -> str:
    """pv_prefix, made instance-specific: a prefix with no macro would name the
    same PVI PV in every instance."""
    p = pv_prefix(placed)
    if "$(" in p or not placed:
        return p
    names = macros_in(placed[0])
    return f"$({names[0]}):" if names else p


def generate(modules: list[str], write: bool):
    """Modules with an override file of their own, one at a time."""
    for m in modules:
        r = process(m, write)
        print(f"== {m} {r['release']}")
        for k, d in r["devices"].items():
            if "error" in d:
                print(f"  {k}: ERROR {d['error']}")
                continue
            print(
                f"  {k}: {d['screen']} via {d['how']}: {d['n_placed']}/{d['n_records']} records placed, "
                f"{len(d['on_screen_not_in_db'])} on screen not in db, {len(d['judgements'])} judgements, "
                f"{len(d['external'])} links not followed"
            )
        for n, why in r["no_screen"]:
            print(f"  (no device) {n}: {why}")
