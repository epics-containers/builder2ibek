"""Tests for the EDM-to-PVI tool. Run: uv run pytest tools/pvi-from-edm"""

import copy
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
import dbparse  # noqa: E402
import edl  # noqa: E402
import gen  # noqa: E402
import release  # noqa: E402
import validate  # noqa: E402
from settings import CFG  # noqa: E402

SCREEN = """4 0 1
beginScreenProperties
major 4
w 400
h 300
endScreenProperties

# (Text Control)
object activeXTextDspClass
beginObjectProperties
x 10
y 10
w 50
h 20
controlPv "$(dev):SP"
editable
visPv "$(dev):MODE"
visMin "1"
visMax "2"
endObjectProperties

# (Text Monitor)
object TextupdateClass
beginObjectProperties
x 70
y 10
w 50
h 20
controlPv "$(dev):SP:RBV"
endObjectProperties
"""


@pytest.mark.parametrize("raw,want", [("Set Point", "SetPoint"), ("8401_asyn", "N8401Asyn"), ("a-b c", "ABC")])
def test_pascal_makes_pvi_names(raw, want):
    assert gen.pascal(raw) == want


@pytest.mark.parametrize(
    "tag,edl_file",
    [
        ("# % gui, $(name=), edm, x.edl, P=$(P)", "x.edl"),
        ("# % gui, $(name=), edm, EDM_FILE=x.edl, P=$(P)", "x.edl"),
        ("# % gui, $(name=), edm, $(EDM_FILE=x.edl), P=$(P)", "x.edl"),
        ("# % gui, $(name=), edmtab, x.edl, P=$(P)", "x.edl"),
    ],
)
def test_gui_tag_forms(tmp_path, tag, edl_file):
    f = tmp_path / "a.template"
    f.write_text(tag + "\n")
    assert dbparse.parse_db(f).gui[0] == (edl_file, {"P": "$(P)"})


def test_edmembed_tag_is_kept_apart(tmp_path):
    f = tmp_path / "a.template"
    f.write_text("# % gui, n, edmembed, x_embed.edl, P=$(P)\n")
    db = dbparse.parse_db(f)
    assert db.gui == [] and db.gui_embed[0][0] == "x_embed.edl"


def test_include_found_in_search_path_and_missing_reported(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (b / "inc.template").write_text('record(ai, "$(P):INC") {}\n')
    (a / "main.template").write_text('include "inc.template"\ninclude "nope.template"\nrecord(ai, "$(P):MAIN") {}\n')
    db = dbparse.parse_db(a / "main.template", search=[b])
    assert set(db.records) == {"$(P):INC", "$(P):MAIN"}
    assert db.missing_includes == ["nope.template"]


def test_compiled_undefined_marks_and_defaults(tmp_path):
    f = tmp_path / "a.db"
    f.write_text('record(ai, "$(P,undefined)$(S=:)X") {}\n')
    db = dbparse.parse_db(f)
    assert list(db.records) == ["$(P)$(S)X"]
    assert db.defaults == {"S": ":"}


def test_infer_env_maps_screen_macro_to_db_macros():
    env = gen.infer_env(["$(dev):SP", "$(dev):RBV"], {"$(P)$(R):SP": 1, "$(P)$(R):RBV": 1})
    assert env["dev"] == "$(P)$(R)"


def test_infer_env_identity_wins():
    assert gen.infer_env(["$(P):SP"], {"$(P):SP": 1})["P"] == "$(P)"


def test_match_tail_needs_a_unique_tail():
    recs = {"$(P):FOO": 1, "$(P):BAR": 1, "$(Q):BAR": 1}
    assert gen.match_tail("$(A):$(B):FOO", recs) == "$(P):FOO"
    assert gen.match_tail("$(A):$(B):BAR", recs) is None


def test_gate_condition_text(tmp_path):
    f = tmp_path / "s.edl"
    f.write_text(SCREEN)
    edl._CACHE.clear()
    o = edl.parse_edl(f).objects[0]
    assert edl.gate_conditions(o, {"dev": "$(P)"}) == [("$(P):MODE", "visible when 1 <= value < 2")]
    assert edl.parse_edl(f) is edl.parse_edl(f)


def test_insert_pvi_only_adds_lines():
    text = "module: m\n\nentity_models:\n  - name: a\n    description: x\n\n  - name: b\n    description: y\n"
    new = gen.insert_pvi(text, "a", gen.pvi_block("a.pvi.device.yaml", {"P": None, "Q": 'x"y'}, "$(P):"))
    assert validate.yaml_only_adds_pvi(text, new) == ""
    data = yaml.safe_load(new)
    assert data["entity_models"][0]["pvi"]["ui_macros"] == {"P": None, "Q": 'x"y'}
    assert "pvi" not in data["entity_models"][1]


def test_empty_ui_macros_is_a_mapping():
    assert yaml.safe_load(gen.pvi_block("a", {}, ""))["pvi"]["ui_macros"] == {}


def test_yaml_change_is_caught():
    assert validate.yaml_only_adds_pvi("a: 1\n", "a: 2\n")


def test_macro_prefix_always_has_a_macro():
    assert gen.macro_prefix(["$(P)A", "$(Q)B"]).startswith("$(")
    assert gen.macro_prefix(["$(P):A", "$(P):B"]) == "$(P):"


def test_build_instance_stubs_objects_with_their_attributes():
    em = {
        "name": "e",
        "parameters": {
            "ctl": {"type": "object", "description": "d"},
            "P": {"type": "str", "description": "d"},
            "N": {"type": "int", "description": "d", "default": 3},
            "E": {"type": "enum", "description": "d", "values": {"a": None}},
        },
        "databases": [{"file": "x", "args": {"Q": "{{ ctl.device }}"}}],
    }
    stubs, ents = validate.build_instance(em, "m")
    assert "device" in stubs[0]["parameters"]
    assert ents[0]["device"] == "TEST-device"
    assert ents[1] == {"type": "m.e", "ctl": ents[0]["name"], "P": "TEST-P", "E": "a"}


def test_msi_expansion_finds_records_and_group(tmp_path):
    if not CFG.msi_path():
        pytest.skip("no msi")
    db = tmp_path / "db"
    rt = tmp_path / "rt"
    db.mkdir()
    rt.mkdir()
    (db / "x.template").write_text('record(ai, "$(P):A") {}\n')
    (rt / "x.pvi.template").write_text('record("*", "$(P):A") {\n info(Q:group, {\n "$(P):PVI": {\n "a": {}\n }\n })\n}\n')
    subst = 'file "$(M)/db/x.template" {\npattern\n { "P" }\n { "T" }\n}\n\nfile "x.pvi.template" {\npattern\n { "P" }\n { "T" }\n}\n\nfile "gone.template" {\npattern\n { "P" }\n { "T" }\n}\n'
    r = validate.expand_db(subst, [db], rt, tmp_path)
    assert r["expander"] == "msi"
    assert set(r["real"]) == {"T:A"} and r["pvi"] == ["T:A"]
    assert r["groups"] == ["T:PVI"]
    assert r["missing_templates"] == ["gone.template"]


def test_version_sort_and_release_pick(tmp_path, monkeypatch):
    assert release.vkey("2-10") > release.vkey("2-9")
    t = tmp_path / "prod" / "support"
    for v in ("1-0", "1-2", "Rx-y"):
        (t / "mod" / v / "data").mkdir(parents=True)
    (t / "mod" / "1-0" / "data" / "a.edl").write_text("")
    monkeypatch.setattr(CFG, "prod", [t])
    monkeypatch.setattr(CFG, "work", [])
    monkeypatch.setattr(CFG, "older", [])
    rel, how = release.pick("mod", "mod", {"version": "1-0"})
    assert rel.name == "1-0" and how.startswith("exact")
    rel, how = release.pick("mod", "mod", {"version": "9"})
    assert rel.name == "1-2"  # no exact match: the newest, with or without screens
    assert release.pick("other", "other", {}) == (None, "no release in any tree")


def test_release_dependencies_follow_includes(tmp_path):
    release.deps.cache_clear()
    dep = tmp_path / "support" / "dep" / "1"
    (dep / "db").mkdir(parents=True)
    rel = tmp_path / "rel"
    (rel / "configure").mkdir(parents=True)
    (rel / "configure" / "RELEASE").write_text("-include $(TOP)/configure/RELEASE.more\n")
    (rel / "configure" / "RELEASE.more").write_text(f"SUPPORT={tmp_path}/support\nDEP=$(SUPPORT)/dep/1\n")
    assert release.deps(rel) == (("DEP", dep),)


def test_header_dropped_when_dedupe_shrinks_a_row():
    ctx = gen.Ctx(module="", release=Path("."), dbs=[], records={}, env={}, roots={}, subst={})
    a = {"type": "SignalR", "name": "A", "read_pv": "$(P):A"}
    tree = [
        {"type": "Group", "name": "G", "layout": {"type": "Grid"}, "children": [dict(a)]},
        {"type": "Group", "name": "R", "layout": {"type": "Row", "header": ["x", "y"]}, "children": [dict(a), {"type": "SignalR", "name": "B", "read_pv": "$(P):B"}]},
    ]
    out = gen.dedupe(tree, ctx)
    assert "header" not in out[1]["layout"]


# --- protected controls ---

import classify  # noqa: E402
import protect  # noqa: E402


def _rw(name, write, read, **kw):
    return {"type": "SignalRW", "name": name, "write_pv": write, "write_widget": {"type": "TextWrite"}, "read_pv": read, "read_widget": {"type": "TextRead"}, **kw}


def _w(name, write, widget=None, **kw):
    return {"type": "SignalW", "name": name, "write_pv": write, "write_widget": dict(widget or {"type": "TextWrite"}), **kw}


def _r(name, read):
    return {"type": "SignalR", "name": name, "read_pv": read, "read_widget": {"type": "TextRead"}}


def _grid(name, kids):
    return {"type": "Group", "name": name, "layout": {"type": "Grid", "labelled": True}, "children": kids}


BUTTONS = {"type": "ButtonPanel", "actions": {"Go": "1", "Halt": "0"}}


def _move(children, targets, dropped=()):
    names = {}

    def unique(base, key):
        n = gen.pascal(base)
        names[n] = key
        return n

    return protect.move(children, dict.fromkeys(targets, "dangerous"), lambda pv: {"type": "TextRead"}, set(dropped), unique)


def _sub(tree):
    return next(c for c in tree if c.get("label") == protect.SUB_LABEL)


def test_no_targets_leaves_the_tree_alone():
    tree = [_grid("A", [_rw("X", "W", "R")])]
    assert _move(tree, []) is tree


def test_paired_write_splits_and_keeps_its_name():
    tree = _move([_grid("A", [_rw("X", "W", "R", label="Lab")])], ["W"])
    assert tree[0]["children"] == [{"name": "X", "label": "Lab", "type": "SignalR", "read_pv": "R", "read_widget": {"type": "TextRead"}}]
    moved = _sub(tree)["children"][0]["children"][0]
    assert (moved["type"], moved["name"], moved["write_pv"], moved["label"]) == ("SignalW", "X", "W", "Lab")
    assert "read_pv" not in moved


def test_single_pv_write_stays_read_write_so_the_last_pvi_record_is_unchanged():
    tree = _move([_grid("A", [_rw("X", "W", "W")])], ["W"])
    assert tree[0]["children"][0]["type"] == "SignalR"
    assert _sub(tree)["children"][0]["children"][0]["type"] == "SignalRW"
    assert tree[-1].get("label") == protect.SUB_LABEL


def test_text_write_leaves_its_value_but_a_button_leaves_nothing():
    tree = _move([_grid("A", [_w("T", "T1"), _w("B", "B1", BUTTONS), _r("Z", "Z1")])], ["T1", "B1"])
    assert [(c["type"], c.get("read_pv")) for c in tree[0]["children"]] == [("SignalR", "T1"), ("SignalR", "Z1")]


@pytest.mark.parametrize("kw,dropped", [({"_read": True}, ()), ({}, ("B1",))])
def test_a_button_whose_record_the_screen_showed_leaves_a_read(kw, dropped):
    tree = _move([_grid("A", [_w("B", "B1", BUTTONS, **kw)])], ["B1"], dropped)
    assert tree[0]["children"][0]["read_pv"] == "B1"


def test_a_group_left_empty_goes():
    tree = _move([_grid("A", [_w("B", "B1", BUTTONS)]), _grid("C", [_r("Z", "Z1")])], ["B1"])
    assert [c["name"] for c in tree] == ["C", "ProtectedControls"]


def test_row_keeps_its_header_when_every_column_stays():
    row = {"type": "Group", "name": "RowX", "label": "L", "layout": {"type": "Row", "header": ["a", "b"]}, "children": [_rw("X", "W", "R"), _r("Y", "Y1")]}
    tree = _move([_grid("A", [row])], ["W"])
    assert tree[0]["children"][0]["layout"]["header"] == ["a", "b"]
    assert _sub(tree)["children"][0]["children"][0]["label"] == "L"


def test_row_drops_its_header_when_a_column_goes():
    row = {"type": "Group", "name": "RowX", "label": "L", "layout": {"type": "Row", "header": ["a", "b"]}, "children": [_w("B", "B1", BUTTONS), _r("Y", "Y1")]}
    tree = _move([_grid("A", [row])], ["B1"])
    assert "header" not in tree[0]["children"][0]["layout"]


def test_guarded_write_stays_behind_its_dialog():
    g = _w("D", "D1", _guarded=True)
    tree = [_grid("A", [g])]
    t, _ = protect.targets_of(tree, [dict(pv="D1", field="", in_db=True)], {("m", "e", "D1"): {"class": "dangerous"}}, "m", "e")
    assert t == {}


def test_targets_mode_only_stays_unplaced_ignored_unlisted_counts_as_unsure():
    tree = [_grid("A", [_w("M", "M1"), _w("D", "D1"), _w("N", "N1"), _w("F", "F1")])]
    gated = [dict(pv=p, field=f, in_db=True) for p, f in (("M1", ""), ("D1", ""), ("N1", ""), ("F1.PROC", "PROC"), ("Gone", ""))]
    classes = {("m", "e", "M1"): {"class": "mode-only"}, ("m", "e", "D1"): {"class": "dangerous"}}
    t, unlisted = protect.targets_of(tree, gated, classes, "m", "e")
    assert t == {"D1": "dangerous", "N1": "unsure"}
    assert unlisted == ["N1"]


def test_verify_move_accepts_a_move_and_catches_anything_else():
    before = [_grid("A", [_rw("X", "W", "R"), _r("Z", "Z1"), _w("K", "K1")])]
    import copy

    after = _move(copy.deepcopy(before), ["W"])
    assert protect.verify_move(before, after, {"W": "dangerous"}) == []
    bad = copy.deepcopy(after)
    bad[0]["children"] = [c for c in bad[0]["children"] if c["name"] != "Z"]
    assert protect.verify_move(before, bad, {"W": "dangerous"})
    bad = copy.deepcopy(after)
    bad[0]["children"].append(_w("X", "W"))
    assert protect.verify_move(before, bad, {"W": "dangerous"})
    bad = copy.deepcopy(after)
    bad[0]["children"][0]["read_pv"] = "Other"
    assert protect.verify_move(before, bad, {"W": "dangerous"})


def test_pvi_formats_the_moved_device(tmp_path):
    from pvi._format.dls import DLSFormatter
    from pvi.device import Device

    row = {"type": "Group", "name": "RowX", "label": "L", "layout": {"type": "Row"}, "children": [_rw("X", "W", "R"), _rw("Y", "W2", "R2")]}
    tree = _move([_grid("A", [row, _w("B", "B1", BUTTONS)])], ["W", "B1"])
    assert all(c["type"] != "Group" for g in _sub(tree)["children"] for c in g["children"])
    DLSFormatter().format(Device(label="d", children=tree), tmp_path / "d.pvi.bob")
    assert (tmp_path / "d_ProtectedControls.pvi.bob").exists()


@pytest.mark.parametrize(
    "bad",
    [
        "- {module: m, entity: e, pv: p, class: safe, evidence: x, judged: read}",
        "- {module: m, entity: e, pv: p, class: unsure}",
        "- {module: m, entity: e, pv: p, class: unsure, evidence: x, judged: read}\n- {module: m, entity: e, pv: p, class: unsure, evidence: x, judged: read}",
    ],
)
def test_a_malformed_class_file_stops_the_run(tmp_path, bad):
    f = tmp_path / "c.yaml"
    f.write_text(bad)
    with pytest.raises(ValueError):
        protect.load_classes(f)


def _ev(**kw):
    return {"module": "m", "entity": "e", "pv": "$(P):THING", "gates": [["$(P):G", "visible when 1 <= value < 2"]], "dialog_text": [], "behind_dialog": False,
            "record": {"desc": ""}, "gate_records": {"$(P):G": {"type": "ai"}}, "screen_warnings": [], "labels": [], **kw}


def test_no_evidence_is_unsure_never_mode_only():
    assert classify.rule_for(_ev())[:2] == ("unsure", "rule:no-rule")


@pytest.mark.parametrize(
    "kw,cls,rule",
    [
        ({"screen_warnings": ["Turning this off will trip the machine!"]}, "dangerous", "rule:warning-text"),
        ({"dialog_text": ["This action can cause a reset, are you sure?"]}, "dangerous", "rule:warning-text"),
        ({"gates": [["", "widget asks for a password"]], "gate_records": {}}, "dangerous", "rule:password-widget"),
        ({"gates": [["$(P):Pwd1_OK_STS", "x"]]}, "dangerous", "rule:password-gate"),
        ({"pv": "$(P):CCHV"}, "dangerous", "rule:name-hv"),
        ({"record": {"desc": "Control Valves"}}, "dangerous", "rule:name-valve"),
        ({"gates": [["$(P):THING.DISA", "x"]]}, "mode-only", "rule:own-disa"),
        ({"gates": [["$(P):SYS_VER", "x"]]}, "mode-only", "rule:capability-gate"),
        ({"gate_records": {"$(P):G": {"type": "mbbo", "states": ["Soft", "External"]}}}, "mode-only", "rule:selector-gate"),
    ],
)
def test_classification_rules(kw, cls, rule):
    assert classify.rule_for(_ev(**kw))[:2] == (cls, rule)


def test_a_legend_or_heading_is_not_a_warning():
    assert classify.rule_for(_ev(screen_warnings=["High Temp Warning  High Temp Trip", "Interlocks"]))[0] == "unsure"


def test_danger_in_the_name_beats_a_mode_selector():
    r = _ev(pv="$(P):RESET", gate_records={"$(P):G": {"type": "mbbo", "states": ["A", "B"]}})
    assert classify.rule_for(r)[0] == "dangerous"


def test_a_person_edit_survives_reclassifying():
    r = _ev()
    old = {("m", "e", "$(P):THING"): dict(module="m", entity="e", pv="$(P):THING", **{"class": "mode-only"}, evidence="I know", judged="person")}
    assert classify.build([r], old)[0]["class"] == "mode-only"
    assert classify.build([r], {})[0]["class"] == "unsure"


def test_doubtful_entries_sort_first():
    a = dict(module="a", entity="e", pv="1", **{"class": "mode-only"}, names_only=False)
    b = dict(module="b", entity="e", pv="2", **{"class": "dangerous"}, names_only=False)
    c = dict(module="c", entity="e", pv="3", **{"class": "unsure"}, names_only=True)
    d = dict(module="d", entity="e", pv="4", **{"class": "dangerous"}, names_only=True)
    assert [x["pv"] for x in sorted([a, b, c, d], key=classify.sort_key)] == ["4", "3", "2", "1"]


# --- record fields ---

import fielddefs  # noqa: E402


def test_dbd_gives_a_record_types_fields():
    text = 'recordtype(foo) {\n\tinclude "dbCommon.dbd"\n\tfield(VAL,DBF_DOUBLE) {\n\t\tprompt("x")\n\t}\n\tfield(MODE,DBF_MENU) {\n\t}\n}\n'
    assert fielddefs.parse_dbd(text) == {"foo": {"VAL": "DBF_DOUBLE", "MODE": "DBF_MENU"}}


@pytest.mark.parametrize(
    "rtype,fld,why",
    [
        ("ao", "PROC", ""),
        ("ao", "HOPR", ""),
        ("ao", "DESC$", ""),
        ("ao", "SEVR", "alarm field"),
        ("ao", "NOSUCH", "not a field of ao"),
        ("nosuchtype", "VAL", "no definition found for record type nosuchtype"),
    ],
)
def test_which_fields_go_in(rtype, fld, why):
    assert fielddefs.left_out_why(rtype, fld, Path("/nonexistent")) == why


FIELD_SCREEN = """4 0 1
beginScreenProperties
major 4
w 400
h 300
endScreenProperties

# (Message Button)
object activeMessageButtonClass
beginObjectProperties
x 10
y 10
w 50
h 20
controlPv "$(dev):REC.PROC"
pressValue "0"
onLabel "Do It"
offLabel "Do It"
endObjectProperties

# (Text Monitor)
object TextupdateClass
beginObjectProperties
x 10
y 50
w 50
h 20
controlPv "$(dev):REC.RBV"
endObjectProperties

# (Text Monitor)
object TextupdateClass
beginObjectProperties
x 10
y 90
w 50
h 20
controlPv "$(dev):REC.SEVR"
endObjectProperties

# (Text Control)
object activeXTextDspClass
beginObjectProperties
x 10
y 130
w 50
h 20
controlPv "$(dev):REC.SCAN"
editable
endObjectProperties
"""


def _field_ctx(tmp_path):
    (tmp_path / "s.edl").write_text(FIELD_SCREEN)
    rec = dbparse.Record(rtype="motor", name="$(dev):REC", fields={})
    return gen.Ctx(module="m", release=Path("/nonexistent"), dbs=[], records={"$(dev):REC": rec}, env={"dev": "$(dev)"}, roots={}, subst={}), tmp_path / "s.edl"


def test_field_widgets_follow_the_motor_pattern(tmp_path):
    ctx, path = _field_ctx(tmp_path)
    groups = gen.layout_screen(ctx, path, ctx.env)
    leaves = {c["name"]: c for c in gen.walk_signals(gen.screen_children(ctx, groups, "s.edl", "d"))}
    button = next(c for c in leaves.values() if c.get("write_pv", "").endswith(".PROC"))
    assert button["type"] == "SignalW" and button["write_widget"] == {"type": "ButtonPanel", "actions": {"DoIt": "0"}}
    assert any(c.get("read_pv", "").endswith(".RBV") for c in leaves.values())
    assert next(c for c in leaves.values() if c.get("write_pv", "").endswith(".SCAN"))["write_widget"] == {"type": "ComboBox"}
    assert not any(".SEVR" in str(c) for c in leaves.values())
    assert ctx.fields_left == {"$(dev):REC.SEVR": "alarm field"}


def test_a_gated_field_write_is_named_with_its_field():
    tree = [_grid("A", [_w("P", "R.PROC", BUTTONS)])]
    t, _ = protect.targets_of(tree, [dict(pv="R.PROC", field="PROC", in_db=True)], {("m", "e", "R.PROC"): {"class": "dangerous"}}, "m", "e")
    assert t == {"R.PROC": "dangerous"}


def test_pvi_writes_an_illegal_record_name_for_a_field(tmp_path):
    """Why the check copy marks its fields for msi. softIocPVA refuses this line."""
    from pvi._format.template import format_template
    from pvi.device import Device

    format_template(Device(label="d", children=[_w("Stop", "$(P).STOP", BUTTONS)]), "$(P):", tmp_path / "t")
    assert 'record("*", "$(P).STOP")' in (tmp_path / "t").read_text()


def test_a_generated_pvi_section_has_no_pv():
    block = gen.pvi_block("d.pvi.device.yaml", {"P": None}, "$(P):")
    assert "pv: true" not in block and "pv_prefix" in block and "ui_macros" in block


def test_marking_fields_keeps_macros_for_msi():
    text = "  read_pv: $(P)A.RBV\n  write_pv: $(P)A.B:C\n  name: X.Y\n  write_pv: $(P)D.PROC\n"
    assert validate.marked_device(text) == "  read_pv: $(P)A__FIELD__RBV\n  write_pv: $(P)A.B:C\n  name: X.Y\n  write_pv: $(P)D__FIELD__PROC\n"


def test_add_pv_true_touches_one_entity():
    text = "entity_models:\n  - name: a\n    pvi:\n      pv_prefix: x\n  - name: b\n    pvi:\n      pv_prefix: y\n"
    out = validate.add_pv_true(text, "b")
    assert out == "entity_models:\n  - name: a\n    pvi:\n      pv_prefix: x\n  - name: b\n    pvi:\n      pv: true\n      pv_prefix: y\n"


def test_a_field_with_no_name_of_its_own_leaves_the_records_name_free(tmp_path):
    (tmp_path / "s.edl").write_text(FIELD_SCREEN.replace("$(dev):REC.RBV", "$(dev).VELO").replace("$(dev):REC.SEVR", "$(dev):VELO"))
    assert gen.suffix_of("$(dev).VELO") == ".VELO"
    recs = {n: dbparse.Record(rtype="ao", name=n, fields={}) for n in ("$(dev)", "$(dev):VELO", "$(dev):REC")}
    ctx = gen.Ctx(module="m", release=Path("/nonexistent"), dbs=[], records=recs, env={"dev": "$(dev)"}, roots={}, subst={})
    leaves = list(gen.walk_signals(gen.screen_children(ctx, gen.layout_screen(ctx, tmp_path / "s.edl", ctx.env), "s.edl", "d")))
    assert {c.get("read_pv"): c["name"] for c in leaves}["$(dev):VELO"] == "Velo"


def test_a_row_named_after_a_signal_doesnt_label_the_moved_write():
    row = {"type": "Group", "name": "RowS", "label": "S", "layout": {"type": "Row"}, "children": [_r("S", "S1"), _rw("Cc", "W", "W")]}
    tree = _move([_grid("A", [row])], ["W"])
    assert _sub(tree)["children"][0]["children"][0]["label"] == "Cc"


# Labels


def text(x, y, w, h, value, **props):
    return edl.Obj("activeXTextClass", x, y, w, h, {"value": value, **props})


def button(x, y, w, h, pv="$(P):GO.PROC", press="1", **props):
    return edl.Obj("activeMessageButtonClass", x, y, w, h, {"controlPv": pv, "pressValue": press, **props})


def layout_ctx(records: dict):
    recs = {k: dbparse.Record(v[0], k, v[1]) for k, v in records.items()}
    return gen.Ctx(module="m", release=Path("/nonexistent"), dbs=[], records=recs, env={}, roots={}, subst={}, sweep=True)


def lay_out(tmp_path, objs, records):
    """Build a screen file from objects, then run the layout and the group builder."""
    lines = ["4 0 1", "beginScreenProperties", "major 4", "w 800", "h 800", "endScreenProperties", ""]
    for o in objs:
        lines += [f"object {o.cls}", "beginObjectProperties", f"x {o.x}", f"y {o.y}", f"w {o.w}", f"h {o.h}"]
        for k, v in o.props.items():
            if isinstance(v, list):
                lines += [f"{k} {{"] + [f'  "{s}"' for s in v] + ["}"]
            elif v is True:
                lines.append(k)
            else:
                lines.append(f'{k} "{v}"')
        lines += ["endObjectProperties", ""]
    f = tmp_path / f"s{len(list(tmp_path.iterdir()))}.edl"
    f.write_text("\n".join(lines))
    ctx = layout_ctx(records)
    ctx.env_cur = {}
    out = []
    with pytest.MonkeyPatch.context() as m:
        # field checks read a release's dbd files, and these screens have no release
        m.setattr(gen, "left_out_why", lambda *a: None)
        for g in gen.layout_screen(ctx, f, {}):
            out += gen.build_group(ctx, g, f.name, g["title"] or "General", {}, "dev")
    return out


def rec(rtype="ai", **fields):
    return (rtype, fields)


def flat(tree):
    return list(gen.walk_signals(tree))


def named(tree, pv):
    return next(c for c in flat(tree) if pv in (c.get("write_pv"), c.get("read_pv")))


def test_a_text_drawn_on_a_button_is_its_label_not_the_text_beside_it(tmp_path):
    objs = [
        text(92, 12, 46, 48, "latched initial current"),
        button(148, 12, 96, 44, "$(P):RESET.PROC"),
        text(148, 12, 96, 44, "Reset Interlocks"),
    ]
    c = named(lay_out(tmp_path, objs, {"$(P):RESET": rec()}), "$(P):RESET.PROC")
    assert c["label"] == "Reset Interlocks"
    assert c["write_widget"]["actions"] == {"ResetInterlocks": "1"}


def test_a_bare_button_takes_the_nearest_text_on_its_row(tmp_path):
    objs = [text(5, 60, 130, 20, "HV Actual Output"), edl.Obj("TextupdateClass", 135, 60, 100, 20, {"controlPv": "$(P):HV"}), button(240, 60, 25, 20, "$(P):HV.PROC")]
    c = named(lay_out(tmp_path, objs, {"$(P):HV": rec()}), "$(P):HV.PROC")
    assert c["write_widget"]["actions"] == {"HvActualOutput": "1"}
    assert c["label"] == "HV Actual Output"


def test_a_bare_button_ignores_a_distant_text_and_uses_its_own_name(tmp_path):
    objs = [text(5, 60, 100, 20, "Unrelated"), button(400, 60, 25, 20, "$(P):GO.PROC")]
    c = named(lay_out(tmp_path, objs, {"$(P):GO": rec()}), "$(P):GO.PROC")
    assert "label" not in c
    assert c["write_widget"]["actions"] == {c["name"]: "1"}


def test_a_button_value_in_words_names_its_action(tmp_path):
    objs = [button(10, 10, 20, 20, "$(P):LENS", press="Out", onLabel=" ", offLabel=" ")]
    c = named(lay_out(tmp_path, objs, {"$(P):LENS": rec("bo")}), "$(P):LENS")
    assert c["write_widget"]["actions"] == {"Out": "Out"}


def test_a_desc_on_a_button_captions_that_button_only(tmp_path):
    def desc(x, pv):
        return edl.Obj("activeXTextDspClass", x + 5, 90, 60, 30, {"controlPv": f"{pv}.DESC"})

    objs = [
        button(10, 90, 80, 30, "$(P):G0.PROC"),
        desc(10, "$(P):G0"),
        button(110, 90, 80, 30, "$(P):G1.PROC"),
        desc(110, "$(P):G1"),
    ]
    tree = lay_out(tmp_path, objs, {"$(P):G0": rec("calcout", DESC="Air"), "$(P):G1": rec("calcout")})
    assert named(tree, "$(P):G0.PROC")["label"] == "Air"
    assert named(tree, "$(P):G1.PROC")["label"] == "G1"
    assert named(tree, "$(P):G0.PROC")["write_widget"]["actions"] == {"Air": "1"}


def test_a_text_under_another_gate_is_an_overlay_not_a_label(tmp_path):
    w = edl.Obj("TextupdateClass", 210, 447, 190, 25, {"controlPv": "$(P):TEMP", "groupVisPv": "$(P):TYPE", "groupVisMin": "0", "groupVisMax": "1"})
    t = text(10, 447, 165, 85, "Drive: Activated", groupVisPv="$(P):TYPE", groupVisMin="1", groupVisMax="2")
    assert gen.is_overlay(t, [w])
    same = text(10, 447, 165, 25, "Temperature", groupVisPv="$(P):TYPE", groupVisMin="0", groupVisMax="1")
    assert not gen.is_overlay(same, [w])


def test_a_text_stacked_on_a_text_widget_is_an_overlay_but_one_beside_it_is_not():
    w = edl.Obj("TextupdateClass", 100, 10, 100, 20, {"controlPv": "$(P):A"})
    assert gen.is_overlay(text(100, 10, 100, 20, "N/A"), [w])
    assert not gen.is_overlay(text(10, 10, 200, 20, "Wide label"), [w])


def test_a_dynamic_desc_row_uses_the_record_default_then_its_name(tmp_path):
    def row(y, pv):
        return [
            edl.Obj("TextupdateClass", 10, y, 200, 25, {"controlPv": f"{pv}.DESC"}),
            edl.Obj("activeXTextDspClass", 210, y, 190, 25, {"controlPv": pv}),
        ]

    tree = lay_out(tmp_path, row(10, "$(P):A") + row(40, "$(P):BACK"), {"$(P):A": rec(DESC="Suct Temp"), "$(P):BACK": rec()})
    assert named(tree, "$(P):A")["label"] == "Suct Temp"
    assert named(tree, "$(P):BACK")["label"] == "BACK"


def test_multi_line_text_spaced_across_rows_labels_each_row(tmp_path):
    lines = ["P2 Setpoint (mbarg)", "", "", "", "P2 Band (mbarg)", "", "", "", "Pump Speed (Hz)"]
    objs = [text(10, 10, 110, 117, lines)]
    recs = {}
    for i, n in enumerate(("A", "B", "C")):
        objs.append(edl.Obj("TextupdateClass", 130, 10 + 52 * i, 100, 15, {"controlPv": f"$(P):{n}"}))
        recs[f"$(P):{n}"] = rec()
    tree = lay_out(tmp_path, objs, recs)
    assert [named(tree, f"$(P):{n}")["label"] for n in "ABC"] == ["P2 Setpoint (mbarg)", "P2 Band (mbarg)", "Pump Speed (Hz)"]


def test_two_lines_with_no_gap_stay_one_wrapped_label(tmp_path):
    objs = [text(10, 10, 80, 50, ["Binning", "Size"])]
    objs += [edl.Obj("TextupdateClass", 100, 10, 100, 20, {"controlPv": "$(P):R"}), edl.Obj("TextentryClass", 100, 35, 100, 20, {"controlPv": "$(P):W"})]
    tree = lay_out(tmp_path, objs, {"$(P):R": rec(), "$(P):W": rec("ao")})
    assert named(tree, "$(P):R")["label"] == "Binning Size"


def test_a_tall_button_does_not_merge_the_rows_it_spans(tmp_path):
    objs = [
        text(5, 320, 90, 35, "Upper Limit"),
        button(100, 320, 75, 80, "$(P):SAVE.PROC"),
        text(100, 320, 75, 80, "Save Limits"),
        edl.Obj("TextentryClass", 180, 320, 130, 35, {"controlPv": "$(P):U"}),
        text(5, 360, 90, 35, "Lower Limit"),
        edl.Obj("TextentryClass", 180, 365, 130, 35, {"controlPv": "$(P):L"}),
    ]
    tree = lay_out(tmp_path, objs, {"$(P):SAVE": rec(), "$(P):U": rec("ao"), "$(P):L": rec("ao")})
    assert named(tree, "$(P):SAVE.PROC")["label"] == "Save Limits"
    assert named(tree, "$(P):U")["label"] == "Upper Limit"
    assert named(tree, "$(P):L")["label"] == "Lower Limit"


def test_a_column_beside_one_tall_widget_takes_its_heading(tmp_path):
    objs = [text(230, 240, 180, 20, "Fatal Errors"), edl.Obj("ByteClass", 390, 260, 20, 80, {"controlPv": "$(P):F"})]
    objs += [text(230, 260 + 20 * i, 90, 20, n) for i, n in enumerate(("Battery", "CPU Bus", "PC Setup", "I/O"))]
    tree = lay_out(tmp_path, objs, {"$(P):F": rec()})
    assert named(tree, "$(P):F")["label"] == "Fatal Errors"


def test_a_column_with_no_heading_is_cut_at_a_whole_item(tmp_path):
    names = [f"Alarm number {i} high" for i in range(8)]
    objs = [edl.Obj("ByteClass", 390, 100, 20, 160, {"controlPv": "$(P):F"})]
    objs += [text(230, 100 + 20 * i, 150, 20, n) for i, n in enumerate(names)]
    label = named(lay_out(tmp_path, objs, {"$(P):F": rec()}), "$(P):F")["label"]
    assert label == "Alarm number 0 high, Alarm number 1 high ..."
    assert len(label) <= gen.LONG_LABEL


@pytest.mark.parametrize(
    "label,junk",
    [
        ("P $(P) R $(Q)", True),
        ("Device $(device) Device_Suffix $(device_suffix)", True),
        ("$(P$(Q):NOMOTOR)", True),
        ("$(device)$(variable)", True),
        ("$(box-label)", True),
        ("$(device):TRIG_MULTI$(id)", True),
        ("Channel $(CHAN_NUM)", False),
        ("Channel $(CHAN_NUM) Scaler Data", False),
        ("LVDT$(lvdtID)", False),
        ("Temperature", False),
    ],
)
def test_junk_macro_labels(label, junk):
    assert gen.junk_label(label) is junk


def test_a_default_in_a_label_macro_shows_its_text():
    assert gen.clean_label("$(CHANN_NAME=Chan1):") == "Chan1"


@pytest.mark.parametrize(
    "symbols,want",
    [("Mass=1,Device=$(P)$(Q)", "Mass 1"), ("P=$(P),R=$(Q)", "detail"), ("", "detail")],
)
def test_a_link_with_no_label_is_named_by_real_values_or_its_screen(tmp_path, symbols, want):
    (tmp_path / "data").mkdir()
    edl_text = "4 0 1\nbeginScreenProperties\nw 100\nh 100\nendScreenProperties\n"
    edl_text += 'object TextupdateClass\nbeginObjectProperties\nx 1\ny 1\nw 50\nh 20\ncontrolPv "$(P):A"\nendObjectProperties\n'
    edl_text += 'object TextupdateClass\nbeginObjectProperties\nx 1\ny 30\nw 50\nh 20\ncontrolPv "$(P):B"\nendObjectProperties\n'
    edl_text += 'object TextupdateClass\nbeginObjectProperties\nx 1\ny 60\nw 50\nh 20\ncontrolPv "$(P):C"\nendObjectProperties\n'
    edl_text += 'object TextupdateClass\nbeginObjectProperties\nx 1\ny 90\nw 50\nh 20\ncontrolPv "$(P):D"\nendObjectProperties\n'
    (tmp_path / "data" / "detail.edl").write_text(edl_text)
    ctx = layout_ctx({f"$(P):{n}": rec() for n in "ABCD"})
    ctx.release = tmp_path
    ctx.env_cur = {}
    ln = {"file": "detail.edl", "label": "", "kind": "related", "symbols": symbols, "obj": button(0, 0, 10, 10), "env": {}}
    got = gen.link_components(ctx, ln, "main.edl", gen.Row(0, 10), "dev")
    assert got[0]["label"] == want


def test_a_macro_with_a_real_value_fills_the_label():
    ctx = layout_ctx({})
    ctx.env_cur = {"M47": "97", "P": "$(P)"}
    assert gen.literal_macros("$(M47)", ctx) == "97"
    assert gen.literal_macros("$(P)", ctx) == "$(P)"


def test_a_long_path_label_keeps_its_end_and_a_sentence_cuts_at_a_word():
    path = gen.shorten("UserGUI / Settings / Heater Control / Settings / Tank 1 Heater and some more words")
    assert path.endswith("Tank 1 Heater and some more words") and len(path) <= gen.LONG_LABEL
    cut = gen.shorten("Write the calibration points above to the PLC. This will only work if unlocked")
    assert cut.endswith(" ...") and len(cut) <= gen.LONG_LABEL and " to the" in cut


def test_a_warning_is_never_shortened_but_other_long_labels_are():
    long = "x " * 40
    tree = [
        {"type": "SignalW", "name": "A", "label": long, "_warning": True},
        {"type": "SignalW", "name": "B", "label": long},
        {"type": "SignalR", "name": "C", "label": "P $(P) R $(Q)"},
    ]
    gen.finish_labels(tree)
    assert tree[0]["label"] == long
    assert len(tree[1]["label"]) <= gen.LONG_LABEL
    assert "label" not in tree[2]


def test_actions_sharing_a_name_are_told_apart_by_value():
    assert gen.button_actions([("", "0"), ("", "1")], "Foo") == {"Foo0": "0", "Foo1": "1"}
    assert gen.button_actions([("<", "1")], "Left") == {"Left": "1"}
    assert gen.button_actions([("Set", "1")], "Foo") == {"Set": "1"}


def sub(children):
    return {"type": "Group", "name": "S", "label": "S", "layout": {"type": "SubScreen", "labelled": False}, "children": children}


def test_a_device_inside_one_sub_screen_is_promoted():
    inner = [{"type": "SignalR", "name": "A", "read_pv": "a"}]
    assert gen.promote_only_screen([sub(inner)], layout_ctx({})) == inner


def test_a_confirmation_sub_screen_and_a_sibling_stop_promotion():
    guarded = [sub([{"type": "SignalW", "name": "A", "write_pv": "a", "_guarded": True}])]
    assert gen.promote_only_screen(guarded, layout_ctx({})) == guarded
    two = [sub([]), {"type": "SignalR", "name": "A", "read_pv": "a"}]
    assert gen.promote_only_screen(two, layout_ctx({})) == two


def test_every_generated_header_warns_about_hand_edits():
    assert gen.REGEN_NOTE.startswith("# ") and "regeneration" in gen.REGEN_NOTE


def test_hygiene_reports_what_the_site_pattern_matches(tmp_path, monkeypatch):
    (tmp_path / "d.pvi.device.yaml").write_text("label: fine\nlabel: SECRET-1\n")
    assert validate.hygiene(tmp_path) == []
    monkeypatch.setattr(CFG, "hygiene_pattern", r"secret-\d")
    assert validate.hygiene(tmp_path) == ["d.pvi.device.yaml:2: label: SECRET-1"]


def test_a_column_beside_several_signals_labels_each_one(tmp_path):
    objs = [
        edl.Obj("TextupdateClass", 100, 10, 60, 30, {"controlPv": "$(P):A"}),
        edl.Obj("TextupdateClass", 170, 30, 60, 30, {"controlPv": "$(P):B"}),
        text(10, 10, 60, 16, "Act"),
        text(10, 40, 60, 16, "Rqs"),
    ]
    tree = lay_out(tmp_path, objs, {"$(P):A": rec(), "$(P):B": rec()})
    assert named(tree, "$(P):A")["label"] == "Act"
    assert named(tree, "$(P):B")["label"] == "Rqs"
    assert not any(c["type"] == "Group" for c in tree)


def test_a_unit_is_a_short_text_just_after_a_widget():
    objs = [edl.Obj("TextupdateClass", 100, 10, 60, 20, {"controlPv": "$(P):A"}), text(10, 10, 60, 20, "Speed")]
    row = gen.Row(10, 30, uses=[gen.Use("$(P):A", "$(P):A", "", "read", objs[0])], texts=[objs[1], text(165, 10, 20, 20, "Hz")])
    ctx = layout_ctx({"$(P):A": rec()})
    assert gen.row_components(ctx, row, "f", "g", {})[0]["label"] == "Speed (Hz)"
    far = gen.Row(10, 30, uses=[gen.Use("$(P):A", "$(P):A", "", "read", objs[0])], texts=[objs[1], text(300, 10, 40, 20, "Moving")])
    ctx = layout_ctx({"$(P):A": rec()})
    assert gen.row_components(ctx, far, "f", "g", {})[0]["label"] == "Speed"


# Several buttons on one PV


def _panel(name, pv, actions, **kw):
    return {"type": "SignalW", "name": name, "write_pv": pv, "write_widget": {"type": "ButtonPanel", "actions": actions}, **kw}


def _dedupe(tree):
    ctx = layout_ctx({})
    return gen.dedupe(tree, ctx), ctx


def test_buttons_with_different_values_merge_in_screen_order():
    tree = [_grid("A", [_panel("Lens", "L", {"Out": "Out"})]), _grid("B", [_panel("Lens", "L", {"In": "In"})])]
    kept, ctx = _dedupe(tree)
    leaves = list(gen.walk_signals(kept))
    assert len(leaves) == 1 and leaves[0]["name"] == "Lens"
    assert list(leaves[0]["write_widget"]["actions"].items()) == [("Out", "Out"), ("In", "In")]
    assert ctx.merged_buttons == {"L": {"Out": "Out", "In": "In"}}
    assert [c["name"] for c in kept] == ["A"]  # the group the second came from is empty


def test_two_buttons_with_one_value_and_label_stay_one():
    kept, ctx = _dedupe([_panel("X", "L", {"Go": "1"}), _panel("X", "L", {"Go": "1"})])
    assert [c["write_widget"]["actions"] for c in gen.walk_signals(kept)] == [{"Go": "1"}]
    assert not ctx.merged_buttons


def test_a_second_label_for_one_value_does_not_add_a_button():
    kept, _ = _dedupe([_panel("X", "L", {"Stop": "1"}), _panel("X", "L", {"Halt": "1"})])
    assert next(gen.walk_signals(kept))["write_widget"]["actions"] == {"Stop": "1"}


def test_one_label_for_two_values_is_told_apart_by_value():
    kept, _ = _dedupe([_panel("X", "L", {"Set": "1"}), _panel("X", "L", {"Set": "2"})])
    assert next(gen.walk_signals(kept))["write_widget"]["actions"] == {"Set1": "1", "Set2": "2"}


def test_a_panel_copy_with_a_readback_takes_the_other_buttons():
    rw = {**_panel("X", "W", {"On": "1"}), "type": "SignalRW", "read_pv": "R", "read_widget": {"type": "LED"}}
    kept, ctx = _dedupe([_panel("X", "W", {"Off": "0"}), rw])
    assert [c["type"] for c in gen.walk_signals(kept)] == ["SignalRW"]
    assert next(gen.walk_signals(kept))["write_widget"]["actions"] == {"Off": "0", "On": "1"}
    assert ctx.merged_buttons["W"] == {"Off": "0", "On": "1"}


def test_a_button_dropped_for_its_dialog_adds_its_value_behind_the_dialog():
    guarded = _panel("X", "W", {"Trip": "1"}, _guarded=True)
    kept, _ = _dedupe([_panel("X", "W", {"Reset": "0"}), {"type": "Group", "name": "D", "layout": {"type": "SubScreen"}, "children": [guarded]}])
    only = list(gen.walk_signals(kept))
    assert len(only) == 1 and only[0]["_guarded"]
    assert only[0]["write_widget"]["actions"] == {"Reset": "0", "Trip": "1"}


def test_a_button_on_a_pv_with_a_text_entry_is_reported_with_why():
    kept, ctx = _dedupe([_w("X", "W", {"type": "TextWrite"}), _panel("X", "W", {"Zero": "0"})])
    assert next(gen.walk_signals(kept))["write_widget"] == {"type": "TextWrite"}
    assert ctx.buttons_covered["W"] == {"values": ["0"], "why": "writable through its TextWrite"}


def test_a_row_holding_a_panel_gives_its_signals_to_the_grid(tmp_path):
    from pvi._format.dls import DLSFormatter
    from pvi.device import Device

    row = {"type": "Group", "name": "RowX", "label": "L", "layout": {"type": "Row"}, "children": [_r("A", "a"), _panel("B", "b", {"In": "1", "Out": "0"})]}
    raw = [_grid("G", [copy.deepcopy(row)])]
    with pytest.raises(AssertionError):
        DLSFormatter().format(Device(label="d", children=gen.clean(raw)), tmp_path / "raw.pvi.bob")
    lifted = gen.lift_panels(raw)
    assert [c["name"] for c in lifted[0]["children"]] == ["A", "B"]
    assert lifted[0]["children"][0]["label"] == "L"
    DLSFormatter().format(Device(label="d", children=gen.clean(lifted)), tmp_path / "d.pvi.bob")


def test_a_merged_panel_writes_each_value_from_its_own_button_in_the_bob(tmp_path):
    import audit
    from pvi._format.dls import DLSFormatter
    from pvi.device import Device

    kept, _ = _dedupe([_grid("A", [_panel("Lens", "L", {"Out": "Out"}), _panel("Lens", "L", {"In": "In"})])])
    DLSFormatter().format(Device(label="d", children=gen.clean(kept)), tmp_path / "d.pvi.bob")
    assert audit.bob_writes(tmp_path / "d.pvi.bob") == {"L": [("Out", "Out"), ("In", "In")]}


def test_a_merged_signal_is_protected_if_any_button_is_gated():
    kept, _ = _dedupe([_grid("A", [_panel("Lens", "L", {"Out": "Out"})]), _grid("B", [_panel("Lens", "L", {"In": "In"})])])
    gated = [dict(pv="L", in_db=True)]  # one gated button is enough: the gate names the PV
    classes = {("m", "e", "L"): dict(**{"class": "unsure"})}
    targets, _ = protect.targets_of(kept, gated, classes, "m", "e")
    assert targets == {"L": "unsure"}
    tree = _move(kept, ["L"])
    assert [c["write_widget"]["actions"] for g in _sub(tree)["children"] for c in g["children"]] == [{"Out": "Out", "In": "In"}]
    assert not [c for c in tree if c.get("label") != protect.SUB_LABEL]


def test_keep_on_main_stays_where_it_is_even_when_gated():
    classes = {("m", "e", "L"): dict(**{"class": "keep-on-main"})}
    targets, unlisted = protect.targets_of([_panel("X", "L", {"Stop": "1"})], [dict(pv="L", in_db=True)], classes, "m", "e")
    assert targets == {} and unlisted == []


def test_a_held_label_is_not_the_buttons_name():
    Obj = edl.Obj
    o = Obj("activeMessageButtonClass", 0, 0, 10, 10, {"onLabel": "Stopping", "offLabel": "Stop"})
    assert gen.own_button_text(o) == "Stop"
    assert gen.own_button_text(Obj("activeMessageButtonClass", 0, 0, 10, 10, {"onLabel": "Go", "offLabel": " "})) == "Go"


def test_password_gates_are_flagged_however_the_entry_was_judged():
    r = _ev(gates=[["$(P)Pwd2_OK_STS", "visible when 1 <= value < 2"]])
    assert classify.password_gated(r)
    assert classify.build([r], {})[0]["password_gated"] is True
    assert "password_gated" not in classify.build([_ev()], {})[0]
    old = {(r["module"], r["entity"], r["pv"]): dict(module="m", entity="e", pv=r["pv"], judged="person:x", names_only=False, **{"class": "dangerous"})}
    assert classify.build([r], old)[0]["password_gated"] is True


def test_a_stop_in_a_sub_screen_comes_to_the_first_screen_and_one_there_stays():
    stop = _panel("Stop", "S", {"Stop": "1"})
    here = _panel("Halt", "H", {"Halt": "1"})
    subscreen = {"type": "Group", "name": "Sub", "layout": {"type": "SubScreen"}, "children": [_grid("In", [stop])]}
    tree, pulled = protect.on_main([_grid("G", [here]), subscreen], {"S", "H"}, lambda base, key: gen.pascal(base))
    assert pulled == ["S"]
    assert [c["name"] for c in tree] == ["StopControls", "G"]  # the sub-screen left empty is gone
    assert tree[0]["children"] == [stop] and tree[1]["children"] == [here]


def test_a_stop_behind_a_dialog_stays_behind_it():
    stop = _panel("Stop", "S", {"Stop": "1"}, _guarded=True)
    tree, pulled = protect.on_main([{"type": "Group", "name": "Sub", "layout": {"type": "SubScreen"}, "children": [stop]}], {"S"}, lambda b, k: b)
    assert pulled == [] and tree[0]["children"] == [stop]


def test_a_toggle_is_named_by_what_its_press_writes_and_keeps_both_values(tmp_path):
    o = edl.Obj("activeMessageButtonClass", 0, 0, 10, 10, {"onLabel": "Disabled", "offLabel": "Enabled", "toggle": True})
    assert gen.own_button_text(o) == "Disabled"
    props = {"onLabel": "Disabled", "offLabel": "Enabled", "toggle": True, "pressValue": "1", "releaseValue": "0"}
    tree = lay_out(tmp_path, [button(10, 10, 60, 20, pv="$(P):GO.DISA", **props)], {"$(P):GO": rec("bo")})
    assert named(tree, "$(P):GO.DISA")["write_widget"]["actions"] == {"Disabled": "1", "Enabled": "0"}


def test_a_screen_with_a_copied_rest_label_uses_the_held_label():
    o = edl.Obj("activeMessageButtonClass", 0, 0, 10, 10, {"onLabel": "Tara", "offLabel": "Reverse"})
    assert gen.own_button_text(o) == "Reverse"
    assert gen.own_button_text(o, "copied.edl") == "Reverse"
    CFG.held_label_screens = {"copied.edl"}
    assert gen.own_button_text(o, "copied.edl") == "Tara"


# Momentary buttons: one value on press, another on release


def _held(tmp_path, pv, record, **props):
    objs = [button(10, 10, 80, 20, pv, press="1", releaseValue="0", **props)]
    return named(lay_out(tmp_path, objs, record), pv)




def test_a_momentary_button_has_both_values_under_the_screens_label(tmp_path):
    c = _held(tmp_path, "$(P)$(M).JOGF", {"$(P)$(M)": rec("motor")}, onLabel="Jogging", offLabel="Jog Forward")
    assert c["write_widget"]["actions"] == {"JogForward": "1", "JogForwardStop": "0"}


@pytest.mark.parametrize("pv,label,want", [("$(P):ABORT", "Abort", "AbortRelease"), ("$(P):STOP", "Stop", "StopRelease"), ("$(P):RESET", "Reset", "ResetRelease")])
def test_stop_is_not_said_of_what_does_not_stop_on_release(tmp_path, pv, label, want):
    c = _held(tmp_path, pv, {pv: rec("bo")}, onLabel=label, offLabel=label)
    assert c["write_widget"]["actions"] == {label: "1", want: "0"}


@pytest.mark.parametrize("label", ["Home", "Go", "Run"])
def test_a_momentary_proc_button_has_only_its_press(tmp_path, label):
    """Any write to .PROC processes the record, so a release would repeat the press."""
    c = _held(tmp_path, "$(P):GO.PROC", {"$(P):GO": rec("bo")}, onLabel=label, offLabel=label)
    assert c["write_widget"]["actions"] == {label: "1"}


def test_a_momentary_button_on_another_field_keeps_its_release(tmp_path):
    c = _held(tmp_path, "$(P)$(M).STOP", {"$(P)$(M)": rec("motor")}, onLabel="Stop", offLabel="Stop")
    assert c["write_widget"]["actions"] == {"Stop": "1", "StopRelease": "0"}


def test_the_real_release_value_is_written(tmp_path):
    objs = [button(10, 10, 80, 20, "$(P):BOOT", press="2", releaseValue="0", onLabel="Reboot", offLabel="Reboot")]
    assert named(lay_out(tmp_path, objs, {"$(P):BOOT": rec("mbbo")}), "$(P):BOOT")["write_widget"]["actions"] == {"Reboot": "2", "RebootRelease": "0"}


def test_a_release_only_button_is_not_momentary(tmp_path):
    objs = [edl.Obj("activeMessageButtonClass", 10, 10, 80, 20, {"controlPv": "$(P):GO", "releaseValue": "1", "onLabel": "Go", "offLabel": "Go"})]
    assert named(lay_out(tmp_path, objs, {"$(P):GO": rec("bo")}), "$(P):GO")["write_widget"]["actions"] == {"Go": "1"}


def test_a_toggle_is_not_momentary(tmp_path):
    props = dict(onLabel="On", offLabel="Off", toggle=True)
    c = _held(tmp_path, "$(P):SW", {"$(P):SW": rec("bo")}, **props)
    assert c["write_widget"]["actions"] == {"On": "1", "Off": "0"}


def test_the_fullest_screen_label_names_a_held_button():
    got = gen.fullest_actions({"Forward": "1", "ForwardStop": "0"}, ["Forward", "Jog Forward"], "$(M).JOGF")
    assert got == {"JogForward": "1", "JogForwardStop": "0"}
    same = gen.fullest_actions({"Stop": "1", "StopRelease": "0"}, ["Stop", "Halt"], "$(M).STOP")
    assert same == {"Stop": "1", "StopRelease": "0"}


def test_a_momentary_class_moves_a_write_nothing_gated():
    tree = [_grid("A", [_w("J", "M.JOGF"), _w("K", "M.KEEP")])]
    classes = {("m", "e", "M.JOGF"): {"class": "momentary"}, ("m", "e", "Gone"): {"class": "momentary"}, ("x", "e", "M.KEEP"): {"class": "momentary"}}
    t, unlisted = protect.targets_of(tree, [], classes, "m", "e")
    assert t == {"M.JOGF": "momentary"}
    assert unlisted == []


def test_a_momentary_write_leaves_a_dialog_for_the_protected_screen(tmp_path):
    ctx = layout_ctx({})
    panel = {"type": "SignalW", "name": "Up", "write_pv": "U", "write_widget": {"type": "ButtonPanel", "actions": {"Up": "1", "UpRelease": "0"}}, "_guarded": True}
    other = {"type": "SignalW", "name": "Set", "write_pv": "S", "write_widget": {"type": "TextWrite"}, "_guarded": True}
    tree = [{"type": "Group", "name": "Dlg", "layout": {"type": "SubScreen", "labelled": False}, "children": [panel, other]}]
    file = tmp_path / "c.yaml"
    file.write_text(yaml.safe_dump([dict(module="m", entity="e", pv="U", evidence="", judged="person", **{"class": "momentary"})]))
    after, targets, _ = gen.protect_writes(tree, ctx, {"protected_file": str(file)}, "m", "e")
    assert targets == {"U": "momentary"}
    assert [c["write_pv"] for g in _sub(after)["children"] for c in g["children"]] == ["U"]
    assert any(c["write_pv"] == "S" and c.get("_guarded") for c in gen.walk_signals([after[0]]))


@pytest.mark.parametrize("cls", ["momentary", "keep-on-main"])
def test_classify_keeps_an_entry_the_evidence_does_not_list(cls):
    prev = {("m", "e", "J"): dict(module="m", entity="e", pv="J", names_only=False, judged="person", evidence="", **{"class": cls})}
    assert [e["pv"] for e in classify.build([], prev)] == ["J"]


def test_stale_report_ignores_entries_placed_by_owner_decision(tmp_path, monkeypatch, capsys):
    import sweep

    monkeypatch.setattr(sweep, "load_classes", lambda: {("m", "e", "J"): {"class": "momentary"}, ("m", "e", "K"): {"class": "keep-on-main"}, ("m", "e", "X"): {"class": "dangerous"}})
    sweep.report_stale([])
    out = capsys.readouterr().out
    assert "1 entries" in out and "'X'" in out


# Labels


def test_a_state_variant_on_a_button_does_not_name_it(tmp_path):
    gate = {"visPv": "$(P):AUTO.B", "visMin": "1", "visMax": "2"}
    objs = [button(148, 12, 96, 44, "$(P):RESET.PROC"), text(148, 12, 96, 44, "Reset (Auto On)", **gate), text(148, 12, 96, 44, "Reset Interlocks", **gate, visInvert=True)]
    objs = [gen.Obj(o.cls, o.x, o.y, o.w, o.h, {("group" + k[0].upper() + k[1:] if k.startswith("vis") else k): v for k, v in o.props.items()}) for o in objs]
    assert gen.not_at_rest(objs[1]) and not gen.not_at_rest(objs[2])
    c = named(lay_out(tmp_path, objs, {"$(P):RESET": rec()}), "$(P):RESET.PROC")
    assert c["label"] == "Reset Interlocks"
    assert c["write_widget"]["actions"] == {"ResetInterlocks": "1"}


def test_a_refresh_icon_says_what_a_blank_button_does(tmp_path):
    objs = [
        text(5, 60, 130, 20, "Upper Limit"),
        edl.Obj("TextupdateClass", 135, 60, 100, 20, {"controlPv": "$(P):ULIM:RBV"}),
        button(240, 60, 25, 20, "$(P):ULIM:RBV.PROC"),
        edl.Obj("activePngClass", 245, 62, 15, 15, {"file": "refresh.png"}),
    ]
    c = named(lay_out(tmp_path, objs, {"$(P):ULIM:RBV": rec()}), "$(P):ULIM:RBV.PROC")
    assert c["write_widget"]["actions"] == {"Refresh": "1"}
    assert c["label"] == "Upper Limit"
    assert c["name"] != "UpperLimit"


def test_another_image_says_nothing(tmp_path):
    objs = [text(5, 60, 130, 20, "Upper Limit"), button(140, 60, 25, 20, "$(P):U.PROC"), edl.Obj("activePngClass", 145, 62, 15, 15, {"file": "logo.png"})]
    assert named(lay_out(tmp_path, objs, {"$(P):U": rec()}), "$(P):U.PROC")["write_widget"]["actions"] == {"UpperLimit": "1"}


def test_a_labelled_field_button_does_not_take_the_name_of_the_value_beside_it(tmp_path):
    objs = [
        text(5, 60, 100, 20, "Current Password"),
        edl.Obj("TextupdateClass", 110, 60, 100, 20, {"controlPv": "$(P):PW_MON"}),
        button(215, 60, 80, 20, "$(P):PW_SEND.PROC", onLabel="Set", offLabel="Set"),
    ]
    tree = lay_out(tmp_path, objs, {"$(P):PW_MON": rec(), "$(P):PW_SEND": rec("bo")})
    assert named(tree, "$(P):PW_SEND.PROC")["name"] != "CurrentPassword"
    assert named(tree, "$(P):PW_MON")["label"] == "Current Password"


# Hand-written folders


def test_the_sweep_refuses_to_reset_a_hand_written_folder():
    import sweep

    CFG.hand_written = {("one", "byhand")}
    with pytest.raises(ValueError, match="by hand"):
        sweep.reset_folder(CFG.repos["one"], "byhand", "byhand.ibek.support.yaml")


def test_a_hand_written_folder_stays_out_of_a_sweep(monkeypatch):
    import sweep

    CFG.hand_written = {("one", "byhand")}
    item = dict(repo="one", dir="byhand", yaml="y", module="m", install={}, has_pvi=False)
    monkeypatch.setattr(sweep, "inventory", lambda: [dict(item)])
    monkeypatch.setattr(sweep, "reserved_stems", lambda items: {})
    monkeypatch.setattr(sweep, "finish", lambda status: None)
    monkeypatch.setattr(sweep, "run_item", lambda it: pytest.fail("the folder was queued"))
    sweep.sweep(["byhand"], jobs=1)
    import json

    assert json.loads((CFG.status / "sweep-status.json").read_text())["byhand"]["status"] == "hand_written"


# Audit of momentary buttons, against .bob files


def _bob(folder, name, pv, actions):
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(f"<widget type='action_button'><text>{t}</text><actions><action type='write_pv'><pv_name>{pv}</pv_name><value>{v}</value></action></actions></widget>" for t, v in actions.items())
    (folder / name).write_text(f"<display>{body}</display>")


def _audit_one(tmp_path, monkeypatch, pv, cls, bob, actions):
    import audit

    monkeypatch.setattr(CFG, "sandbox", tmp_path / "sandbox")
    _bob(tmp_path / "sandbox" / "m" / "opi", bob, pv, actions)
    found = [["m", "d", pv, "1", "0"]]
    classes = [dict(module="m", entity="e", pv=pv, **{"class": cls})]
    return audit.audit_momentary(found, classes, {("m", "e"): ("m", {"file_stem": "d"})})["bad"]


def test_audit_passes_a_proc_press_alone_on_protected(tmp_path, monkeypatch):
    assert _audit_one(tmp_path, monkeypatch, "R.PROC", "momentary", "d_ProtectedControls.pvi.bob", {"Home": "1"}) == []


def test_audit_fails_a_release_action_on_proc(tmp_path, monkeypatch):
    assert _audit_one(tmp_path, monkeypatch, "R.PROC", "momentary", "d_ProtectedControls.pvi.bob", {"Home": "1", "HomeRelease": "0"})


def test_audit_fails_a_lost_release_on_another_field(tmp_path, monkeypatch):
    assert _audit_one(tmp_path, monkeypatch, "M.JOGF", "momentary", "d_ProtectedControls.pvi.bob", {"Jog": "1"})


def test_audit_wants_a_stop_on_the_first_screen(tmp_path, monkeypatch):
    assert _audit_one(tmp_path, monkeypatch, "M.STOP", "keep-on-main", "d.pvi.bob", {"Stop": "1", "StopRelease": "0"}) == []
    assert _audit_one(tmp_path, monkeypatch, "N.STOP", "keep-on-main", "d_ProtectedControls.pvi.bob", {"Stop": "1", "StopRelease": "0"})
