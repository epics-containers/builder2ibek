"""Deterministic parser for EDM .edl files (format 4.x, keyword properties).

EDM is positional: nothing here relies on object order in the file. Objects
inside an activeGroupClass keep absolute coordinates, so groups are flattened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OBJ_RE = re.compile(r"^object\s+(\S+)")
MACRO = re.compile(r"\$\((\w+)\)")


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.replace('\\"', '"').replace("\\\\", "\\")


@dataclass
class Obj:
    cls: str
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    props: dict = field(default_factory=dict)
    line: int = 0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    def get(self, k, default=None):
        return self.props.get(k, default)

    def contains(self, other: "Obj", tol: int = 2) -> bool:
        return (
            self.x - tol <= other.cx <= self.x2 + tol
            and self.y - tol <= other.cy <= self.y2 + tol
        )


@dataclass
class Screen:
    path: Path
    w: int = 0
    h: int = 0
    title: str = ""
    bg: int | None = None
    objects: list[Obj] = field(default_factory=list)
    format_ok: bool = True


_CACHE: dict[str, "Screen"] = {}


def parse_edl(path: Path) -> Screen:
    """Parsed once per file; callers treat the result as read-only."""
    key = str(path)
    if key not in _CACHE:
        _CACHE[key] = _parse_edl(path)
    return _CACHE[key]


def _parse_edl(path: Path) -> Screen:
    lines = Path(path).read_text(errors="replace").splitlines()
    scr = Screen(path=Path(path))
    i = 0
    # screen properties
    while i < len(lines) and lines[i].strip() != "beginScreenProperties":
        i += 1
    if i >= len(lines):
        scr.format_ok = False
        return scr
    i += 1
    head: dict = {}
    while i < len(lines) and lines[i].strip() != "endScreenProperties":
        k, _, v = lines[i].strip().partition(" ")
        head[k] = v
        i += 1
    scr.w = int(head.get("w", 0) or 0)
    scr.h = int(head.get("h", 0) or 0)
    scr.title = _unquote(head.get("title", ""))
    if m := re.match(r"index (\d+)", head.get("bgColor", "")):
        scr.bg = int(m.group(1))
    # objects: flat scan; beginGroup/endGroup nest but children are absolute
    stack: list[Obj] = []
    cur: Obj | None = None
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        i += 1
        if not s or s.startswith("#"):
            continue
        if m := OBJ_RE.match(s):
            cur = Obj(cls=m.group(1), line=i)
            continue
        if cur is None:
            continue
        if s == "beginObjectProperties":
            cur.props["_first_child"] = len(scr.objects)
            stack.append(cur)
            continue
        if s in ("beginGroup", "endGroup"):
            # children of a group are parsed as ordinary objects
            if s == "endGroup":
                cur = stack[-1] if stack else None
            continue
        if s == "endObjectProperties":
            done = stack.pop() if stack else cur
            if done.cls != "activeGroupClass":
                scr.objects.append(done)
            elif done.get("visPv"):
                # visibility on a group applies to everything inside it
                for child in scr.objects[done.props["_first_child"] :]:
                    if "groupVisPv" not in child.props:
                        child.props["groupVisPv"] = done.get("visPv")
                        for k in ("visMin", "visMax", "visInvert"):
                            if k in done.props:
                                child.props["group" + k[0].upper() + k[1:]] = done.props[k]
            cur = stack[-1] if stack else None
            continue
        target = stack[-1] if stack else cur
        k, _, v = s.partition(" ")
        v = v.strip()
        if v == "{":
            items = []
            while i < n and lines[i].strip() != "}":
                items.append(lines[i].strip())
                i += 1
            i += 1
            target.props[k] = _parse_array(items)
            continue
        if k in ("x", "y", "w", "h") and re.fullmatch(r"-?\d+", v or ""):
            setattr(target, k, int(v))
            continue
        target.props[k] = _unquote(v) if v else True
    return scr


def _parse_array(items: list[str]) -> list | dict:
    """EDL arrays are either bare strings or `index "value"` pairs."""
    pairs: dict[int, str] = {}
    bare: list[str] = []
    for it in items:
        if m := re.match(r"(\d+)\s+(.*)$", it):
            pairs[int(m.group(1))] = _unquote(m.group(2))
        elif it:
            bare.append(_unquote(it))
    if pairs and not bare:
        return [pairs[k] for k in sorted(pairs)]
    return bare + [pairs[k] for k in sorted(pairs)]


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


# Which property carries which role, per widget class.
READ_CLASSES = {
    "activeXTextDspClass:noedit",
    "TextupdateClass",
    "activeMeterClass",
    "activeLogMeterClass",
    "activeBarClass",
    "activeVsBarClass",
    "activeIndicatorClass",
    "ByteClass",
    "multiLineTextUpdateClass",
    "activeSymbolClass",
    "activeDynSymbolClass",
    "activeCoefTableClass",
    "activeTableClass",
    "xyGraphClass",
    "StripClass",
}
WRITE_CLASSES = {
    "TextentryClass",
    "activeMenuButtonClass",
    "activeChoiceButtonClass",
    "activeRadioButtonClass",
    "activeMessageButtonClass",
    "activeButtonClass",
    "activeUpdownButtonClass",
    "activeSliderClass",
    "activeMotifSliderClass",
    "activeMpStrobeClass",
    "activeRampButtonClass",
    "multiLineTextEntryClass",
}
CHROME_CLASSES = {
    "activeXTextClass",
    "activeRectangleClass",
    "activeCircleClass",
    "activeLineClass",
    "activeArcClass",
    "activePngClass",
    "cfcf6c8a_dbb0_11d2_8a97_00104b8742df",
    "activeExitButtonClass",
    "shellCmdClass",
    "relatedDisplayClass",
    "activePipClass",
    "activeMenuMuxClass",
    "menuMuxClass",
}
DECOR_PROPS = (
    "visPv",
    "groupVisPv",
    "colorPv",
    "alarmPv",
    "fgAlarm",
    "fillPv",
    "lineColorPv",
    "fillColorPv",
)


def split_pv(raw: str) -> tuple[str, str]:
    """Return (kind, pv). kind: ca|loc|calc|const."""
    if raw is None:
        return "ca", ""
    r = raw.strip()
    if r.upper().startswith("LOC\\") or r.upper().startswith("LOC:"):
        return "loc", r
    if r.upper().startswith("CALC\\"):
        return "calc", r
    if r.upper().startswith("CONST\\") or r.startswith("LOG\\"):
        return "const", r
    for pre in ("EPICS\\", "CA\\", "ca://", "pva://", "PVA\\"):
        if r.startswith(pre):
            r = r[len(pre) :]
    return "ca", r


CALC_ARGS = re.compile(r"\(([^()]*)\)\s*$")


def calc_pvs(raw: str) -> list[str]:
    """PVs passed as arguments to a CALC\\ expression."""
    m = CALC_ARGS.search(raw)
    if not m:
        return []
    out = []
    for a in m.group(1).split(","):
        a = a.strip()
        if a and not re.fullmatch(r"[-+\d.eE]+", a) and "$" in a:
            out.append(a)
    return out


@dataclass
class PvUse:
    pv: str
    role: str  # read | write | decor
    prop: str
    obj: Obj


def pv_uses(o: Obj) -> list[PvUse]:
    """Every EPICS PV the object refers to, with its role."""
    out: list[PvUse] = []

    def add(raw, role, prop):
        if not raw or not isinstance(raw, str):
            return
        kind, pv = split_pv(raw)
        if kind == "calc":
            for a in calc_pvs(raw):
                out.append(PvUse(a, "decor", prop + ":calc", o))
        elif kind == "ca" and pv:
            out.append(PvUse(pv, role, prop, o))

    c = o.cls
    if c == "activeXTextDspClass":
        # an editable text display is a text entry; the rest are read-only
        role = "write" if o.get("editable") else "read"
        add(o.get("controlPv"), role, "controlPv")
    elif c in WRITE_CLASSES:
        add(o.get("controlPv"), "write", "controlPv")
        add(o.get("indicatorPv"), "read", "indicatorPv")
        add(o.get("readPv"), "read", "readPv")
    elif c in READ_CLASSES:
        for p in ("controlPv", "readPv", "indicatorPv", "yPv", "xPv"):
            add(o.get(p), "read", p)
        for p in ("controlPvs", "readPvs", "yPvs", "xPvs"):
            for v in as_list(o.get(p)):
                add(v, "read", p)
        for v in as_list(o.get("traceCtls")):
            add(v, "read", "traceCtls")
    elif c in ("activeCircleClass", "activeRectangleClass"):
        # a filled shape driven by a PV is how EDM draws an LED
        add(o.get("alarmPv"), "led", "alarmPv")
        add(o.get("visPv"), "decor", "visPv")
    elif c == "activeLineClass":
        add(o.get("alarmPv"), "decor", "alarmPv")
    if c not in ("activeCircleClass", "activeRectangleClass"):
        for p in DECOR_PROPS:
            add(o.get(p), "decor", p)
    else:
        for p in ("colorPv", "fillPv", "lineColorPv", "fillColorPv"):
            add(o.get(p), "led" if p == "colorPv" else "decor", p)
    return out


def text_of(o: Obj) -> str:
    v = o.get("value")
    if isinstance(v, list):
        return " ".join(s.strip() for s in v).strip()
    return (v or "").strip() if isinstance(v, str) else ""


def text_lines(o: Obj) -> list[str]:
    """The lines of a text, blank ones kept: they space the rest out."""
    v = o.get("value")
    if isinstance(v, list):
        return [s.strip() for s in v]
    return [v.strip()] if isinstance(v, str) else []


def links(o: Obj) -> list[dict]:
    """Related displays and embedded screens of the object."""
    if o.cls == "relatedDisplayClass":
        files = as_list(o.get("displayFileName"))
        labels = as_list(o.get("menuLabel"))
        syms = as_list(o.get("symbols"))
        out = []
        for i, f in enumerate(files):
            out.append(
                dict(
                    kind="related",
                    file=f,
                    label=(labels[i] if i < len(labels) else "") or o.get("buttonLabel", ""),
                    symbols=syms[i] if i < len(syms) else "",
                    obj=o,
                )
            )
        return out
    if o.cls == "activePipClass":
        files = as_list(o.get("displayFileName")) or as_list(o.get("file"))
        labels = as_list(o.get("menuLabel"))
        syms = as_list(o.get("symbols"))
        out = []
        for i, f in enumerate(files):
            out.append(
                dict(
                    kind="pip",
                    file=f,
                    label=labels[i] if i < len(labels) else "",
                    symbols=syms[i] if i < len(syms) else "",
                    filepv=o.get("filePv", ""),
                    source=o.get("displaySource", "file"),
                    obj=o,
                )
            )
        return out
    return []


def parse_symbols(s: str, env: dict | None = None) -> dict[str, str]:
    """`a=b, c=$(d)` to a dict, expanding against env."""
    out: dict[str, str] = {}
    env = env or {}
    for part in (s or "").split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = expand(v.strip(), env)
    return out


def expand(s: str, env: dict) -> str:
    return MACRO.sub(lambda m: env.get(m.group(1), m.group(0)), s)


def gate_conditions(o: Obj, env: dict) -> list[tuple[str, str]]:
    """(gating PV, condition) for each visibility rule on a widget or its group.

    EDM shows the widget while the value is in [visMin, visMax), or outside that
    range when visInvert is set.
    """
    out = []
    for pv_key, pre in (("visPv", "vis"), ("groupVisPv", "groupVis")):
        pv = o.get(pv_key)
        if not pv:
            continue
        pv = expand(pv, env)
        lo, hi = o.get(pre + "Min"), o.get(pre + "Max")
        rng = f"{lo} <= value < {hi}" if lo is not None or hi is not None else "value nonzero"
        out.append((pv, f"visible when not ({rng})" if o.get(pre + "Invert") else f"visible when {rng}"))
    return out
