"""Unit tests for `builder2ibek.catio.substitute`.

Pure module -- no fastcs_catio, no file I/O.
"""

from __future__ import annotations

import pytest

from builder2ibek.catio.diagnostics import DiagnosticLog
from builder2ibek.catio.substitute import (
    LEGACY_PV_RE,
    NewPv,
    Substituter,
    link_is_reading,
)

# A read-only EL1014 channel and a read/write EL2024-0010 channel, as
# chains.build_substituter would produce them.
DI_IN = "BL21I-DI-ERIO-10:MOD1:CHANNEL1:INPUT"
DI_IN_NEW = "BL21I-DI-E1RIO-10:24VDI01:Channel1"
DI_OUT = "BL21I-DI-ERIO-10:MOD2:CHANNEL1:OUTPUT"
DI_OUT_W = "BL21I-DI-E1RIO-10:12VDO01:Channel1"
DI_OUT_R = "BL21I-DI-E1RIO-10:12VDO01:Channel1_RBV"

SCANNER = "BL21I-DI-IOC-01"
CONSUMER = "BL21I-DI-IOC-04"


def make_substituter(**kwargs) -> Substituter:
    """A Substituter over the two demo PVs, with overridable dictionaries."""
    subs = {
        DI_IN: NewPv.same(DI_IN_NEW),
        DI_OUT: NewPv(read=DI_OUT_R, write=DI_OUT_W),
    }
    owners = {DI_IN: SCANNER, DI_OUT: SCANNER}
    kwargs.setdefault("subs", subs)
    kwargs.setdefault("owners", owners)
    kwargs.setdefault("unresolved", {})
    kwargs.setdefault("known_labels", {"BL21I-DI-ERIO-10": SCANNER})
    return Substituter(**kwargs)


def rewrite(sub: Substituter, value: str, *, attribute: str = "INP", **kwargs) -> str:
    # note: an empty DiagnosticLog is falsy (__len__ == 0), so no `or` here
    log = kwargs.pop("log", None)
    if log is None:
        log = DiagnosticLog()
    return sub.rewrite_value(
        value,
        attribute=attribute,
        log=log,
        ioc=kwargs.pop("ioc", CONSUMER),
        entity=kwargs.pop("entity", "demo"),
    )


# -- NewPv ------------------------------------------------------------------


def test_new_pv_same_sets_both_directions():
    pv = NewPv.same("X:Y")
    assert (pv.read, pv.write, pv.writable) == ("X:Y", "X:Y", False)


def test_new_pv_distinct_is_writable():
    assert NewPv(read="X:Y_RBV", write="X:Y").writable


# -- link direction ---------------------------------------------------------


@pytest.mark.parametrize("flag", ["CP", "CPP", "MS", "MSS", "MSI"])
def test_rule1_read_flags_win(flag):
    # rule 1 beats an output-looking attribute name
    assert link_is_reading("OUT", flag) is True


@pytest.mark.parametrize("flag", ["PP", "NPP"])
def test_rule2_write_flags(flag):
    assert link_is_reading("INP", flag) is False


@pytest.mark.parametrize("attribute", ["OUT", "out3", "DOL", "OUTPUT", "a_out_b"])
def test_rule3_output_attribute_names(attribute):
    assert link_is_reading(attribute, "") is False


@pytest.mark.parametrize("attribute", ["INP", "inp2", "INPUT", "IN", "a_in_b"])
def test_rule4_input_attribute_names(attribute):
    assert link_is_reading(attribute, "") is True


def test_rule5_undecidable_returns_none():
    assert link_is_reading("VAL", "") is None
    assert link_is_reading("rio_dinput", "") is None


@pytest.mark.parametrize("attribute", ["INPA", "INPL", "OUTGB0", "OUTHIS"])
def test_epics_calc_link_names_are_undecidable_by_name(attribute):
    """The specified regexes need a digit or a `_` boundary after `inp`/`out`.

    `INPA`..`INPL` and femto200's `OUTGB0`/`OUTHIS` therefore fall through to
    rule 5. In practice rules 1-2 decide them: the real femto200 values carry
    `PP`. Anything left over defaults to reading and warns for a writable leaf.
    """
    assert link_is_reading(attribute, "") is None
    assert link_is_reading(attribute, "PP") is False


def test_read_flag_beats_write_flag():
    assert link_is_reading("VAL", "PP CP") is True


# -- rewrite_value ----------------------------------------------------------


def test_trailing_flag_and_whitespace_preserved():
    sub = make_substituter()
    assert (
        rewrite(sub, f"{DI_IN} CP", attribute="VAL") == f"{DI_IN_NEW} CP"
    )  # only the PV token changed


def test_odd_whitespace_runs_survive_byte_for_byte():
    sub = make_substituter()
    out = rewrite(sub, f"  {DI_IN}\t\t CP  MS ", attribute="VAL")
    assert out == f"  {DI_IN_NEW}\t\t CP  MS "


def test_writable_leaf_read_via_cp_flag():
    sub = make_substituter()
    assert rewrite(sub, f"{DI_OUT} CP", attribute="VAL") == f"{DI_OUT_R} CP"


def test_writable_leaf_written_via_pp_flag():
    sub = make_substituter()
    assert rewrite(sub, f"{DI_OUT} PP", attribute="VAL") == f"{DI_OUT_W} PP"


def test_writable_leaf_written_via_attribute_name():
    sub = make_substituter()
    assert rewrite(sub, DI_OUT, attribute="OUT") == DI_OUT_W


def test_writable_leaf_read_via_attribute_name():
    sub = make_substituter()
    assert rewrite(sub, DI_OUT, attribute="INP1") == DI_OUT_R


def test_link_direction_guess_only_for_writable_leaf():
    sub = make_substituter()
    log = DiagnosticLog()
    # read-only leaf, undecidable attribute -> no warning
    assert rewrite(sub, DI_IN, attribute="VAL", log=log) == DI_IN_NEW
    assert len(log) == 0
    # writable leaf, undecidable attribute -> reading, plus a warning
    assert rewrite(sub, DI_OUT, attribute="VAL", log=log) == DI_OUT_R
    codes = [d.code for d in log]
    assert codes == ["link-direction-guess"]
    guess = next(iter(log))
    assert (guess.ioc, guess.entity, guess.attribute) == (CONSUMER, "demo", "VAL")
    assert guess.chain == SCANNER


# -- unresolved -------------------------------------------------------------


def test_unresolved_token_diagnosed_and_left_in_place():
    pv = "BL21I-DI-ERIO-01:MOD5:CHANNEL1:INPUT"
    sub = make_substituter(
        unresolved={pv: ("ambiguous-legacy-pv", "two couplers claim MOD5", SCANNER)}
    )
    log = DiagnosticLog()
    assert rewrite(sub, f"{pv} CP", attribute="VAL", log=log) == f"{pv} CP"
    (diag,) = list(log)
    assert diag.code == "ambiguous-legacy-pv"
    assert diag.message == "two couplers claim MOD5"
    assert diag.chain == SCANNER
    assert diag.ioc == CONSUMER
    # the IOC still counts as depending on the chain that blocked it
    assert sub.references(CONSUMER) == {SCANNER}
    assert sub.touched_iocs() == set()


# -- unknown tokens ---------------------------------------------------------


def test_known_label_with_bad_mod_is_mod_out_of_range():
    sub = make_substituter()
    log = DiagnosticLog()
    bad = "BL21I-DI-ERIO-10:MOD99:CHANNEL1:INPUT"
    assert rewrite(sub, bad, attribute="VAL", log=log) == bad
    (diag,) = list(log)
    assert diag.code == "mod-out-of-range"
    assert diag.chain == SCANNER
    assert "BL21I-DI-ERIO-10" in diag.message
    assert "MOD99:CHANNEL1:INPUT" in diag.message
    assert sub.references(CONSUMER) == {SCANNER}


def test_unknown_label_fails_the_consumer_not_a_chain():
    sub = make_substituter()
    log = DiagnosticLog()
    bad = "BL21I-XX-ERIO-77:MOD1:CHANNEL1:INPUT"
    assert rewrite(sub, bad, attribute="VAL", log=log) == bad
    (diag,) = list(log)
    assert diag.code == "unknown-chain-label"
    assert diag.chain is None
    assert diag.ioc == CONSUMER
    assert sub.references(CONSUMER) == set()


def test_non_pv_strings_are_untouched_and_undiagnosed():
    sub = make_substituter()
    log = DiagnosticLog()
    for value in [
        "some free text about ERIO couplers",
        "BL21I-DI-ERIO-10",  # no colon, so not a PV reference
        "1.5",
        "",
        "   ",
    ]:
        assert rewrite(sub, value, attribute="VAL", log=log) == value
    assert len(log) == 0


def test_legacy_pv_re_needs_a_colon_and_an_erio_segment():
    assert LEGACY_PV_RE.match(DI_IN)
    assert not LEGACY_PV_RE.match("BL21I-DI-ERIO-10")
    assert not LEGACY_PV_RE.match("BL21I-DI-VALV-01:STA")


# -- multiple PVs -----------------------------------------------------------


def test_two_pvs_in_one_value_both_rewritten():
    sub = make_substituter()
    out = rewrite(sub, f"{DI_IN} {DI_OUT}", attribute="INP")
    assert out == f"{DI_IN_NEW} {DI_OUT_R}"


def test_second_pv_is_rewritten_even_when_the_first_is_unresolved():
    pv = "BL21I-DI-ERIO-10:MOD9:CHANNEL1:INPUT"
    sub = make_substituter(
        unresolved={pv: ("ambiguous-legacy-pv", "dropped", SCANNER)},
    )
    log = DiagnosticLog()
    out = rewrite(sub, f"{pv} {DI_IN} CP", attribute="VAL", log=log)
    assert out == f"{pv} {DI_IN_NEW} CP"
    assert [d.code for d in log] == ["ambiguous-legacy-pv"]


# -- rewrite_entity ---------------------------------------------------------


def test_rewrite_entity_rewrites_strings_and_reports_change():
    sub = make_substituter()
    log = DiagnosticLog()
    entity = {
        "type": "calc.CalcOut",
        "name": "myCalc",
        "INPA": f"{DI_IN} CP",
        "OUT": DI_OUT,
        "SCAN": "1 second",
        "PREC": 3,
    }
    assert sub.rewrite_entity(entity, log=log, ioc=CONSUMER) is True
    assert entity["INPA"] == f"{DI_IN_NEW} CP"
    assert entity["OUT"] == DI_OUT_W
    assert entity["SCAN"] == "1 second"
    assert entity["PREC"] == 3
    assert entity["type"] == "calc.CalcOut"
    assert len(log) == 0


def test_rewrite_entity_never_rewrites_the_type_key():
    sub = make_substituter(subs={"calc.CalcOut": NewPv.same("REWRITTEN")}, owners={})
    entity = {"type": "calc.CalcOut", "name": "myCalc"}
    assert sub.rewrite_entity(entity, log=DiagnosticLog(), ioc=CONSUMER) is False
    assert entity["type"] == "calc.CalcOut"


def test_rewrite_entity_returns_false_when_nothing_matched():
    sub = make_substituter()
    entity = {"type": "asyn.AsynIP", "name": "port", "P": "BL21I-DI-01"}
    assert sub.rewrite_entity(entity, log=DiagnosticLog(), ioc=CONSUMER) is False


def test_rewrite_entity_passes_the_entity_name_to_diagnostics():
    sub = make_substituter()
    log = DiagnosticLog()
    # INP decides by rule 4, VAL falls through to the guess
    entity = {"type": "calc.Calc", "name": "myCalc", "INP": DI_OUT, "VAL": DI_OUT}
    sub.rewrite_entity(entity, log=log, ioc=CONSUMER)
    (diag,) = list(log)
    assert diag.code == "link-direction-guess"
    assert diag.entity == "myCalc"
    assert diag.attribute == "VAL"


def test_rewrite_entity_tolerates_a_missing_name():
    sub = make_substituter()
    log = DiagnosticLog()
    entity = {"type": "calc.Calc", "VAL": DI_OUT}
    assert sub.rewrite_entity(entity, log=log, ioc=CONSUMER) is True
    (diag,) = list(log)
    assert diag.entity is None


# -- bookkeeping ------------------------------------------------------------


def test_references_and_touched_iocs():
    sub = make_substituter()
    log = DiagnosticLog()
    rewrite(sub, DI_IN, attribute="INP", log=log, ioc="BL21I-DI-IOC-02")
    rewrite(sub, "nothing here", attribute="INP", log=log, ioc="BL21I-DI-IOC-03")
    assert sub.references("BL21I-DI-IOC-02") == {SCANNER}
    assert sub.references("BL21I-DI-IOC-03") == set()
    assert sub.references("never-seen") == set()
    assert sub.touched_iocs() == {"BL21I-DI-IOC-02"}


def test_references_returns_a_copy():
    sub = make_substituter()
    rewrite(sub, DI_IN, attribute="INP")
    got = sub.references(CONSUMER)
    got.add("mutated")
    assert sub.references(CONSUMER) == {SCANNER}


def test_identical_replacement_counts_as_a_reference_but_not_a_rewrite():
    sub = make_substituter(subs={DI_IN: NewPv.same(DI_IN)}, owners={DI_IN: SCANNER})
    assert rewrite(sub, DI_IN, attribute="INP") == DI_IN
    assert sub.references(CONSUMER) == {SCANNER}
    assert sub.touched_iocs() == set()
