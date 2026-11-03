#!/usr/bin/env python3
"""Move visibility-gated writes judged dangerous or unsure into one sub-screen per
device. The classification file holds the judgements, and the generator reads it on every
run. A gated write with no entry there counts as unsure.

A pvi record stays what it was: the write keeps its signal name in the sub-screen
and its readback keeps the same name on the main screen, so `pvi.<name>.r` and
`pvi.<name>.w` are unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from settings import CFG  # noqa: E402

SUB_LABEL = "Protected Controls"
MAIN_LABEL = "Stop Controls"
CLASSES = {"dangerous", "keep-on-main", "mode-only", "momentary", "unsure"}
MOVED = {"dangerous", "momentary", "unsure"}
UNGATED = {"keep-on-main", "momentary"}  # placed by owner decision: the evidence need not list them
FIELDS = ("module", "entity", "pv", "class", "evidence", "judged")


def load_classes(path: Path | None = None) -> dict[tuple[str, str, str], dict]:
    """(module, entity, pv) -> entry. A malformed or missing file stops the run; with no
    file configured there are no entries, so every gated write counts as unsure."""
    path = path or CFG.classification
    if path is None:
        return {}
    entries = yaml.safe_load(path.read_text()) or []
    out: dict[tuple[str, str, str], dict] = {}
    for i, e in enumerate(entries):
        missing = [f for f in FIELDS if f not in e]
        if missing:
            raise ValueError(f"{path.name} entry {i}: missing {', '.join(missing)}")
        if e["class"] not in CLASSES:
            raise ValueError(f"{path.name} entry {i}: class `{e['class']}` is not one of {sorted(CLASSES)}")
        key = (e["module"], e["entity"], e["pv"])
        if key in out:
            raise ValueError(f"{path.name} entry {i}: {key} is listed twice")
        out[key] = e
    return out


def walk_leaves(tree):
    for c in tree:
        if c["type"] == "Group":
            yield from walk_leaves(c["children"])
        else:
            yield c


def targets_of(children: list[dict], gated: list[dict], classes: dict, module: str, entity: str) -> tuple[dict, list[str]]:
    """Writes to move, pv -> class, and the gated writes with no entry in the file."""
    written = {c["write_pv"] for c in walk_leaves(children) if "write_pv" in c and not c.get("_guarded")}
    targets: dict[str, str] = {}
    unlisted: set[str] = set()
    for g in gated:
        pv = g["pv"]
        if not g["in_db"] or pv not in written:
            continue
        entry = classes.get((module, entity, pv))
        if entry is None:
            unlisted.add(pv)
        cls = entry["class"] if entry else "unsure"
        if cls in MOVED:
            targets[pv] = cls
    # a momentary button need not be gated on its screen
    for (mod, ent, pv), entry in classes.items():
        if (mod, ent) == (module, entity) and entry["class"] == "momentary" and pv in written:
            targets[pv] = "momentary"
    return targets, sorted(unlisted)


def _is_button(c: dict) -> bool:
    return c.get("write_widget", {}).get("type") == "ButtonPanel"


def split(c: dict, read_widget_of, dropped_reads: set) -> tuple[dict, dict | None]:
    """A write to its sub-screen form and what stays on the main screen.

    A write widget that shows its own value (text, combo, toggle) leaves a read of
    that value behind. A button shows nothing, so it leaves a read only if the
    screen also showed the record.
    """
    keep = {k: c[k] for k in ("name", "label", "_x") if k in c}
    write = dict(c)
    if c["type"] == "SignalRW" and c["read_pv"] != c["write_pv"]:
        write = {k: v for k, v in c.items() if k not in ("read_pv", "read_widget")}
        write["type"] = "SignalW"
        return write, {**keep, "type": "SignalR", "read_pv": c["read_pv"], "read_widget": c["read_widget"]}
    if c["type"] == "SignalRW":
        return write, {**keep, "type": "SignalR", "read_pv": c["read_pv"], "read_widget": c["read_widget"]}
    if _is_button(c) and not c.get("_read") and c["write_pv"] not in dropped_reads:
        return write, None
    return write, {**keep, "type": "SignalR", "read_pv": c["write_pv"], "read_widget": read_widget_of(c["write_pv"])}


def move(children: list[dict], targets: dict, read_widget_of, dropped_reads: set, unique_name) -> list[dict]:
    """The device tree with targeted writes in one sub-screen at its end.

    pvi nests no Group(Grid) inside a Group(Grid) and asserts on a ButtonPanel in a
    Row, so the sub-screen holds one flat Grid per group the writes came from.
    """
    if not targets:
        return children
    origins: dict[tuple, list[dict]] = {}
    written: set[str] = set()
    read_left: set[str] = set()

    def take(c: dict, path: tuple, row: dict | None) -> dict | None:
        write, read = split(c, read_widget_of, dropped_reads)
        if row is not None and "label" not in write:
            # a row named after its first signal says nothing about the others
            title = row.get("label")
            write["label"] = title if title and title != row["children"][0]["name"] else write["name"]
        if c["write_pv"] not in written:
            written.add(c["write_pv"])
            origins.setdefault(path, []).append(write)
        if read is None or read["read_pv"] in read_left:
            return None
        read_left.add(read["read_pv"])
        return read

    def visit(tree: list[dict], path: tuple) -> list[dict]:
        out = []
        for c in tree:
            if c["type"] == "Group":
                is_row = c["layout"]["type"] == "Row"
                if is_row:
                    n = len(c["children"])
                    kids = []
                    for k in c["children"]:
                        if "write_pv" in k and k["write_pv"] in targets and not k.get("_guarded"):
                            left = take(k, path, c)
                            if left is not None:
                                kids.append(left)
                        else:
                            kids.append(k)
                    if len(kids) != n and c["layout"].get("header"):
                        c["layout"].pop("header")  # its columns no longer line up
                    c["children"] = kids
                else:
                    c["children"] = visit(c["children"], (*path, c.get("label") or c["name"]))
                if c["children"]:
                    out.append(c)
            elif "write_pv" in c and c["write_pv"] in targets and not c.get("_guarded"):
                left = take(c, path, None)
                if left is not None:
                    out.append(left)
            else:
                out.append(c)
        return out

    rest = visit(children, ())
    grids = []
    for path, signals in origins.items():
        title = " / ".join(path) or "General"
        grids.append(
            {
                "type": "Group",
                "name": unique_name("Protected " + title, "protected:" + title),
                "label": title,
                "layout": {"type": "Grid", "labelled": True},
                "children": signals,
            }
        )
    rest.append(
        {
            "type": "Group",
            "name": unique_name(SUB_LABEL, "protected"),
            "label": SUB_LABEL,
            "layout": {"type": "SubScreen", "labelled": False},
            "children": grids,
        }
    )
    return rest


def on_main(children: list[dict], pvs: set[str], unique_name) -> tuple[list[dict], list[str]]:
    """Writes the owner wants quick to reach, on the device's first screen: any that sit
    in a sub-screen go to one grid at its top. Those already there stay where they are."""
    pulled: list[dict] = []

    def visit(tree: list[dict], deep: bool) -> list[dict]:
        out = []
        for c in tree:
            if c["type"] == "Group":
                n = len(c["children"])
                c["children"] = visit(c["children"], deep or c["layout"]["type"] == "SubScreen")
                if len(c["children"]) != n and c["layout"].get("header"):
                    c["layout"].pop("header")  # its columns no longer line up
                if c["children"]:
                    out.append(c)
            elif deep and c.get("write_pv") in pvs and not c.get("_guarded"):
                pulled.append(c)
            else:
                out.append(c)
        return out

    rest = visit(children, False)
    if not pulled:
        return rest, []
    grid = {
        "type": "Group",
        "name": unique_name(MAIN_LABEL, "main-screen-stops"),
        "label": MAIN_LABEL,
        "layout": {"type": "Grid", "labelled": True},
        "children": pulled,
    }
    return [grid, *rest], [c["write_pv"] for c in pulled]


def _shape(c: dict) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in c.items() if not k.startswith("_")))


def verify_move(before: list[dict], after: list[dict], targets: dict) -> list[str]:
    """What, if anything, changed besides the move. Empty when it is only the move."""
    problems = []
    sub = [c for c in after if c["type"] == "Group" and c.get("label") == SUB_LABEL]
    if len(sub) > 1:
        problems.append("more than one protected sub-screen")
    main = [c for c in after if not (c["type"] == "Group" and c.get("label") == SUB_LABEL)]
    moved = list(walk_leaves(sub[0]["children"])) if sub else []
    target_leaves = [c for c in walk_leaves(before) if c.get("write_pv") in targets and not c.get("_guarded")]
    left_behind = {(c["name"], c.get("read_pv") or c["write_pv"]) for c in target_leaves}
    leaves_a = list(walk_leaves(main))
    kept_b = [_shape(c) for c in walk_leaves(before) if not (c.get("write_pv") in targets and not c.get("_guarded"))]
    kept_a = [_shape(c) for c in leaves_a if not (c["type"] == "SignalR" and (c["name"], c["read_pv"]) in left_behind)]
    if kept_a != kept_b:
        problems.append("signals other than the moved writes changed")
    for c in leaves_a:
        if c.get("write_pv") in targets and not c.get("_guarded"):
            problems.append(f"`{c['write_pv']}` is still writable on the main screen")
    if {c["write_pv"] for c in moved} != set(targets):
        problems.append("the sub-screen does not hold exactly the moved writes")
    for grid in sub[0]["children"] if sub else []:
        if any(c["type"] == "Group" for c in grid["children"]):
            problems.append("a Group nested in a sub-screen grid")
    before_w = {c["write_pv"] for c in walk_leaves(before) if "write_pv" in c}
    after_w = {c["write_pv"] for c in leaves_a if "write_pv" in c} | {c["write_pv"] for c in moved}
    if before_w != after_w:
        problems.append("the set of writes changed")
    before_r = {c["read_pv"] for c in walk_leaves(before) if c.get("read_pv")}
    after_r = {c["read_pv"] for c in leaves_a if c.get("read_pv")} | {c["read_pv"] for c in moved if c.get("read_pv")}
    if not before_r <= after_r:
        problems.append("a readback is gone: " + ", ".join(sorted(before_r - after_r)[:3]))
    if after_r - before_r - set(targets):
        problems.append("a new read of another record: " + ", ".join(sorted(after_r - before_r - set(targets))[:3]))
    return problems
