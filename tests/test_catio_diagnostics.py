"""Unit tests for `builder2ibek.catio.diagnostics`."""

import json

import pytest

from builder2ibek.catio.diagnostics import (
    CODES,
    STRICT_PROMOTIONS,
    Diagnostic,
    DiagnosticLog,
    Severity,
)


def test_every_code_has_a_severity():
    assert set(CODES) == {
        "mod-out-of-range",
        "leaf-type-mismatch",
        "coupler-label-conflict",
        "unknown-chain-label",
        "unknown-terminal-type",
        "unknown-entity-type",
        "unmapped-suffix",
        "ambiguous-legacy-pv",
        "shortened-leaf",
        "duplicate-coupler-label",
        "ambiguous-legacy-pv-unused",
        "device-mod-mismatch",
        "unlabelled-coupler",
        "device-without-mod",
        "slave-type-mismatch",
        "link-direction-guess",
        "dropped-reference",
    }
    assert all(isinstance(s, Severity) for s in CODES.values())


@pytest.mark.parametrize("code", sorted(CODES))
def test_default_severity_is_recorded(code):
    log = DiagnosticLog()
    assert log.add(code, "detail").severity is CODES[code]


def test_strict_promotions_are_warnings_by_default():
    assert STRICT_PROMOTIONS == frozenset({"device-mod-mismatch"})
    assert all(CODES[c] is Severity.WARNING for c in STRICT_PROMOTIONS)


@pytest.mark.parametrize("code", sorted(CODES))
def test_strict_promotes_only_the_listed_codes(code):
    strict = DiagnosticLog(strict=True)
    expected = Severity.ERROR if code in STRICT_PROMOTIONS else CODES[code]
    assert strict.add(code, "detail").severity is expected


def test_unknown_code_is_rejected():
    log = DiagnosticLog()
    with pytest.raises(KeyError, match="unknown diagnostic code 'no-such-code'"):
        log.add("no-such-code", "detail")
    assert len(log) == 0


def test_add_returns_and_stores_all_location_fields():
    log = DiagnosticLog()
    diagnostic = log.add(
        "mod-out-of-range",
        "MOD9 exceeds 8 terminals",
        chain="BL21I-VA-IOC-01",
        ioc="BL21I-VA-IOC-05",
        entity="VAFAN4",
        attribute="rio_dinput",
    )
    assert list(log) == [diagnostic]
    assert diagnostic == Diagnostic(
        code="mod-out-of-range",
        severity=Severity.ERROR,
        message="MOD9 exceeds 8 terminals",
        chain="BL21I-VA-IOC-01",
        ioc="BL21I-VA-IOC-05",
        entity="VAFAN4",
        attribute="rio_dinput",
    )
    assert str(diagnostic) == (
        "error [mod-out-of-range] BL21I-VA-IOC-05, entity VAFAN4, "
        "arg rio_dinput: MOD9 exceeds 8 terminals"
    )


def test_errors_and_warnings_partition_the_log():
    log = DiagnosticLog()
    error = log.add("unmapped-suffix", "AL_STATE")
    warning = log.add("unlabelled-coupler", "no DEVICE")
    assert log.errors == [error]
    assert log.warnings == [warning]
    assert len(log) == 2
    assert log.has_errors()


def test_no_errors_when_only_warnings():
    log = DiagnosticLog()
    log.add("slave-type-mismatch", "EL1014 declared, EL1004 found")
    assert not log.has_errors()
    assert log.failed_chains() == set()
    assert log.failed_iocs() == set()


def test_failed_chains_and_iocs_come_from_errors_only():
    log = DiagnosticLog()
    log.add("unmapped-suffix", "AL_STATE", chain="CHAIN-A", ioc="IOC-1")
    log.add("shortened-leaf", "truncated", chain="CHAIN-B")
    log.add("ambiguous-legacy-pv", "two targets", ioc="IOC-2")
    # warnings must not condemn a chain or an IOC
    log.add("link-direction-guess", "assumed read", chain="CHAIN-C", ioc="IOC-3")
    assert log.failed_chains() == {"CHAIN-A", "CHAIN-B"}
    assert log.failed_iocs() == {"IOC-1", "IOC-2"}


def test_strict_failure_sets_propagate():
    log = DiagnosticLog(strict=True)
    log.add("device-mod-mismatch", "MOD3 at position 4", chain="CHAIN-A", ioc="IOC-1")
    assert log.failed_chains() == {"CHAIN-A"}
    assert log.failed_iocs() == {"IOC-1"}


def test_render_groups_errors_before_warnings_and_sorts_chains():
    log = DiagnosticLog()
    # deliberately added out of order
    log.add("unlabelled-coupler", "w-zeta", chain="CHAIN-Z")
    log.add("unmapped-suffix", "e-no-chain")
    log.add("unmapped-suffix", "e-beta", chain="CHAIN-B")
    log.add("shortened-leaf", "e-alpha", chain="CHAIN-A")
    log.add("device-without-mod", "w-no-chain")
    report = log.render()
    assert report.splitlines() == [
        "ERRORS",
        "  chain CHAIN-A",
        "    error [shortened-leaf] chain CHAIN-A: e-alpha",
        "  chain CHAIN-B",
        "    error [unmapped-suffix] chain CHAIN-B: e-beta",
        "  (no chain)",
        "    error [unmapped-suffix]: e-no-chain",
        "",
        "WARNINGS",
        "  chain CHAIN-Z",
        "    warning [unlabelled-coupler] chain CHAIN-Z: w-zeta",
        "  (no chain)",
        "    warning [device-without-mod]: w-no-chain",
        "",
        "3 errors, 2 warnings",
    ]


def test_render_ordering_is_independent_of_insertion_order():
    entries = [
        ("unmapped-suffix", "m1", "CHAIN-B", "IOC-2"),
        ("mod-out-of-range", "m2", "CHAIN-A", "IOC-1"),
        ("unmapped-suffix", "m3", "CHAIN-A", "IOC-1"),
        ("link-direction-guess", "m4", "CHAIN-A", "IOC-3"),
        ("unlabelled-coupler", "m5", None, None),
    ]
    forward = DiagnosticLog()
    backward = DiagnosticLog()
    for code, message, chain, ioc in entries:
        forward.add(code, message, chain=chain, ioc=ioc)
    for code, message, chain, ioc in reversed(entries):
        backward.add(code, message, chain=chain, ioc=ioc)
    assert forward.render() == backward.render()


def test_render_of_empty_log_is_just_the_summary():
    assert DiagnosticLog().render() == "0 errors, 0 warnings"


def test_render_summary_counts_all_diagnostics():
    log = DiagnosticLog()
    log.add("unmapped-suffix", "a", chain="CHAIN-A")
    log.add("shortened-leaf", "b", chain="CHAIN-A")
    log.add("unlabelled-coupler", "c", chain="CHAIN-A")
    assert log.render().endswith("\n\n2 errors, 1 warnings")


def test_to_json_is_serialisable_and_ordered():
    log = DiagnosticLog()
    log.add("unmapped-suffix", "second-added-first", chain="CHAIN-A", ioc="IOC-1")
    log.add(
        "link-direction-guess",
        "guess",
        chain="CHAIN-B",
        ioc="IOC-2",
        entity="femto200",
        attribute="OUTGB0",
    )
    payload = log.to_json()
    assert json.loads(json.dumps(payload)) == payload
    assert [d["message"] for d in payload] == ["second-added-first", "guess"]
    assert payload[1] == {
        "code": "link-direction-guess",
        "severity": "warning",
        "message": "guess",
        "chain": "CHAIN-B",
        "ioc": "IOC-2",
        "entity": "femto200",
        "attribute": "OUTGB0",
    }
    assert all(isinstance(d["severity"], str) for d in payload)


def test_diagnostic_str_omits_absent_location_parts():
    assert str(Diagnostic("shortened-leaf", Severity.ERROR, "boom")) == (
        "error [shortened-leaf]: boom"
    )
    assert str(
        Diagnostic("shortened-leaf", Severity.ERROR, "boom", chain="CHAIN-A")
    ) == ("error [shortened-leaf] chain CHAIN-A: boom")
    assert str(
        Diagnostic(
            "shortened-leaf", Severity.ERROR, "boom", chain="CHAIN-A", ioc="IOC-1"
        )
    ) == ("error [shortened-leaf] IOC-1: boom")
