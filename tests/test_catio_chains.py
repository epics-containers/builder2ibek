"""Tests for `builder2ibek.catio.chains`.

Split deliberately in two. Everything that is pure topology -- bus walking,
coupler labels, ordinal allocation, diagnostics -- runs under plain
``uv run pytest``, because builder2ibek's own environment must never depend on
`fastcs_catio`. Only the tests that assert real fastcs-catio PV names are gated
behind ``pytest.importorskip``; run those with ``.venv-catio/bin/python -m
pytest``.

Fixtures live in ``tests/samples/catio/`` and are byte-identical copies of the
BL21I BUILDER XMLs. Note their ``node`` is **0-based** while
:class:`~builder2ibek.catio.chains.Slave.node` is 1-based (node 0 means "ahead
of the first coupler", as in fastcs-catio), so comparisons add one.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from builder2ibek.builder import Builder
from builder2ibek.catio.chains import (
    Chain,
    Slave,
    UnresolvedMap,
    _locate,
    _split_type_rev,
    build_substituter,
    catio_ioc_name,
    discover_chains,
    domain_of,
    is_scanner,
    parse_chain,
    predict_prefixes,
    report_unused_ambiguities,
)
from builder2ibek.catio.diagnostics import DiagnosticLog, Severity

SAMPLES = Path(__file__).parent / "samples" / "catio"
SCANNERS = ["BL21I-DI-IOC-01", "BL21I-VA-IOC-01", "BL21I-VA-IOC-05", "BL21I-VA-IOC-06"]
CONSUMERS = ["BL21I-VA-IOC-02", "BL21I-VA-IOC-04"]


@pytest.fixture(scope="module")
def expected_chains() -> dict:
    return json.loads((SAMPLES / "expected_chains.json").read_text())


@pytest.fixture(scope="module")
def expected_references() -> list[dict]:
    return json.loads((SAMPLES / "expected_references.json").read_text())


def parsed(scanner: str, log: DiagnosticLog | None = None, **kwargs) -> Chain:
    """Parse one sample scanner. Beware: an empty DiagnosticLog is falsy."""
    if log is None:
        log = DiagnosticLog(**kwargs)
    chain = parse_chain(SAMPLES / f"{scanner}.xml", log, ordinal=1)
    assert chain is not None
    return chain


def codes(log: DiagnosticLog) -> Counter:
    return Counter(d.code for d in log)


# -- helpers -----------------------------------------------------------------


def test_split_type_rev_handles_a_missing_rev_part():
    assert _split_type_rev("EL3104 rev 0x00120000") == ("EL3104", 0x00120000)
    assert _split_type_rev("EL2024-0010") == ("EL2024-0010", None)
    assert _split_type_rev("EL3104 rev not-a-number") == ("EL3104", None)


def test_catio_ioc_name_renames_only_a_whole_ioc_segment():
    assert catio_ioc_name("BL21I-VA-IOC-01") == "BL21I-VA-CATIO-01"
    assert catio_ioc_name("BL21I-IOCX-IOC-01") == "BL21I-IOCX-CATIO-01"


def test_domain_of_takes_the_first_two_segments():
    assert domain_of("BL21I-VA-IOC-01") == "BL21I-VA"


def test_chain_properties_are_the_single_source_of_the_name_templates():
    chain = Chain("BL21I-VA-IOC-05", "BL21I-VA", 2)
    assert chain.catio_ioc == "BL21I-VA-CATIO-05"
    assert chain.services_folder == "bl21i-va-catio-05"
    assert chain.node_prefix == "BL21I-VA-E2RIO-{:02d}"
    assert chain.name_mappings() == {
        "device_prefix": chain.device_prefix,
        "node_prefix": chain.node_prefix,
        "module_prefix": chain.module_prefix,
    }


# -- UnresolvedMap -----------------------------------------------------------


def test_unresolved_map_prefix_lookup_requires_a_colon_boundary():
    entry = ("unknown-entity-type", "no table", "BL21I-DI-IOC-01")
    unresolved = UnresolvedMap()
    unresolved.add_prefix("BL21I-DI-LED-01", entry)
    assert unresolved.get("BL21I-DI-LED-01:CHANNEL1:OUTPUT") == entry
    # a longer sibling name must not be swallowed by the shorter prefix
    assert unresolved.get("BL21I-DI-LED-011:CHANNEL1:OUTPUT") is None
    assert unresolved.get("BL21I-DI-LED-01") is None


def test_unresolved_map_prefers_exact_keys_and_the_longest_prefix():
    exact = ("unmapped-suffix", "exact", None)
    short = ("unknown-entity-type", "short", None)
    long_ = ("unknown-entity-type", "long", None)
    unresolved = UnresolvedMap({"A:MOD1:X": exact})
    unresolved.add_prefix("A", short)
    unresolved.add_prefix("A:MOD1", long_)
    assert unresolved.get("A:MOD1:X") == exact
    assert unresolved.get("A:MOD1:Y") == long_
    assert unresolved.get("A:MOD2:Y") == short
    # membership and indexing stay exact -- only get() consults prefixes
    assert "A:MOD1:Y" not in unresolved


# -- scanner detection and topology ------------------------------------------


def test_is_scanner_picks_exactly_the_four_scanners():
    found = []
    for xml in sorted(SAMPLES.glob("*.xml")):
        builder = Builder()
        builder.load(xml)
        if is_scanner(builder):
            found.append(xml.stem)
    assert found == SCANNERS
    assert not set(found) & set(CONSUMERS)


def test_parse_chain_returns_none_for_a_consumer_only_ioc():
    log = DiagnosticLog()
    assert parse_chain(SAMPLES / "BL21I-VA-IOC-02.xml", log, ordinal=1) is None
    assert len(log) == 0


@pytest.mark.parametrize("scanner", SCANNERS)
def test_chain_topology_matches_the_fixture(scanner, expected_chains):
    chain = parsed(scanner)
    want = [
        # the fixture numbers couplers from 0, Slave.node from 1
        (
            coupler["node"] + 1,
            t["position"],
            t["type_name"],
            t["declared_device"] or None,
            t["entity_type"],
        )
        for coupler in expected_chains[scanner]["couplers"]
        for t in coupler["terminals"]
    ]
    got = [
        (s.node, s.position, s.type_name, s.declared_device, s.entity_type)
        for s in chain.slaves
    ]
    assert got == want


@pytest.mark.parametrize("scanner", SCANNERS)
def test_slave_names_and_revisions_match_the_fixture(scanner, expected_chains):
    chain = parsed(scanner)
    want = [
        (t["slave_name"], int(t["revision"], 16))
        for coupler in expected_chains[scanner]["couplers"]
        for t in coupler["terminals"]
    ]
    assert [(s.slave_name, s.revision) for s in chain.slaves] == want


@pytest.mark.parametrize("scanner", SCANNERS)
def test_coupler_labels_match_the_fixture(scanner, expected_chains):
    chain = parsed(scanner)
    want = {c["node"] + 1: c["label"] for c in expected_chains[scanner]["couplers"]}
    assert chain.labels == want


def test_ek1122_consumes_an_ordinary_position_not_a_node():
    """`EK1122` is a junction, not a coupler: `EK` is not `E[PQR]`."""
    assert _locate(["EK1100", "EL3104", "EK1122", "EL1014"]) == [
        (1, 0, "coupler"),
        (1, 1, "slave"),
        (1, 2, "slave"),
        (1, 3, "slave"),
    ]
    chain = parsed("BL21I-DI-IOC-01")
    junctions = [s for s in chain.slaves if s.type_name == "EK1122"]
    assert junctions, "the DI chain should carry EK1122 junctions"
    assert all(s.category == "slave" and s.position > 0 for s in junctions)
    # node 8 (fixture node 7) ends in a junction at position 20, after MOD15
    node8 = [s for s in chain.slaves if s.node == 8]
    assert (node8[-1].type_name, node8[-1].position) == ("EK1122", 20)


def test_the_coupler_itself_is_position_zero():
    chain = parsed("BL21I-VA-IOC-01")
    couplers = [s for s in chain.slaves if s.category == "coupler"]
    assert len(couplers) == 5
    assert all(s.position == 0 and s.type_name == "EK1100" for s in couplers)


# -- label derivation --------------------------------------------------------


def test_va05_third_coupler_is_unlabelled():
    log = DiagnosticLog()
    chain = parsed("BL21I-VA-IOC-05", log)
    assert chain.labels == {1: "BL21I-VA-ERIO-05", 2: "BL21I-VA-ERIO-06", 3: None}
    unlabelled = [d for d in log if d.code == "unlabelled-coupler"]
    assert len(unlabelled) == 1
    assert unlabelled[0].severity is Severity.WARNING
    assert unlabelled[0].chain == "BL21I-VA-IOC-05"
    assert not log.has_errors()


def test_va06_label_comes_from_the_declaration_not_the_comment():
    """The XML comment says ERIO-05; the only `DEVICE=` says ERIO-99."""
    log = DiagnosticLog()
    chain = parsed("BL21I-VA-IOC-06", log)
    assert chain.labels == {1: "BL21I-VA-ERIO-99"}
    assert len(log) == 0


def test_two_couplers_sharing_a_label_is_a_warning_not_a_failure():
    log = DiagnosticLog()
    chain = parsed("BL21I-DI-IOC-01", log)
    assert chain.labels[8] == chain.labels[9] == "BL21I-DI-ERIO-01"
    duplicates = [d for d in log if d.code == "duplicate-coupler-label"]
    assert len(duplicates) == 1
    assert duplicates[0].severity is Severity.WARNING
    assert not log.has_errors()
    assert "BL21I-DI-IOC-01" not in log.failed_chains()


def test_devices_without_a_mod_part_are_ignored_for_label_derivation():
    log = DiagnosticLog()
    chain = parsed("BL21I-DI-IOC-01", log)
    without = [d for d in log if d.code == "device-without-mod"]
    assert len(without) == 6
    assert all(d.severity is Severity.WARNING for d in without)
    assert {d.entity for d in without} == {
        "D1.Led",
        "D2.Led",
        "D3A.Led",
        "FS1.Led",
        "M1.Piezo",
        "M2.Piezo",
    }
    assert all(d.attribute == "DEVICE" for d in without)
    # node 7 has two such entities and nothing else, so it ends up unlabelled
    assert chain.labels[7] is None


def test_unlabelled_couplers_are_exactly_the_four_the_fixture_names():
    log = DiagnosticLog()
    chain = parsed("BL21I-DI-IOC-01", log)
    assert [n for n, label in chain.labels.items() if label is None] == [1, 5, 6, 7]
    assert codes(log)["unlabelled-coupler"] == 4


def test_disagreeing_devices_on_one_coupler_are_a_label_conflict(tmp_path):
    xml = tmp_path / "BL99Z-XX-IOC-01.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n'
        '<components arch="linux-x86_64">\n'
        '<ethercat.EthercatMaster name="ECATM" socket="/tmp/socket0"/>\n'
        '<ethercat.EthercatSlave master="ECATM" name="C1" type_rev="EK1100 rev 0x1"/>\n'
        '<ethercat.EthercatSlave master="ECATM" name="T1" type_rev="EL3104 rev 0x1"/>\n'
        '<ethercat.EthercatSlave master="ECATM" name="T2" type_rev="EL3104 rev 0x1"/>\n'
        '<ethercat.auto_EL3104 DEVICE="BL99Z-XX-ERIO-01:MOD1" PORT="T1" name="A"/>\n'
        '<ethercat.auto_EL3104 DEVICE="BL99Z-XX-ERIO-02:MOD2" PORT="T2" name="B"/>\n'
        "</components>\n"
    )
    log = DiagnosticLog()
    chain = parse_chain(xml, log, ordinal=1)
    assert chain is not None
    assert chain.labels == {1: None}
    conflicts = [d for d in log if d.code == "coupler-label-conflict"]
    assert len(conflicts) == 1
    assert conflicts[0].severity is Severity.ERROR
    assert log.failed_chains() == {"BL99Z-XX-IOC-01"}


# -- declaration cross-checks ------------------------------------------------


def test_mod1_restart_raises_device_mod_mismatch_at_warning():
    log = DiagnosticLog()
    parsed("BL21I-VA-IOC-01", log)
    mismatches = [d for d in log if d.code == "device-mod-mismatch"]
    # ERIO-04 and ERIO-03 each restart at MOD1 for their two EL1014s
    assert len(mismatches) == 4
    assert all(d.severity is Severity.WARNING for d in mismatches)
    assert not log.has_errors()


def test_device_mod_mismatch_becomes_an_error_under_strict():
    log = DiagnosticLog(strict=True)
    parsed("BL21I-VA-IOC-01", log)
    mismatches = [d for d in log if d.code == "device-mod-mismatch"]
    assert len(mismatches) == 4
    assert all(d.severity is Severity.ERROR for d in mismatches)
    assert log.failed_chains() == {"BL21I-VA-IOC-01"}


def test_non_numeric_mod_names_never_raise_device_mod_mismatch():
    """`MODSAM3`..`MODSAM7` are opaque labels, not bus positions."""
    log = DiagnosticLog()
    chain = parsed("BL21I-DI-IOC-01", log)
    sam = [
        s
        for s in chain.slaves
        if (s.declared_device or "").startswith("BL21I-DI-ERIO-05:MODSAM")
    ]
    assert len(sam) == 5
    flagged = {d.entity for d in log if d.code == "device-mod-mismatch"}
    assert not flagged & {s.entity_name for s in sam}


def test_slave_type_mismatch_is_a_warning():
    """Five `EL2024` slaves are bound to `auto_EL2024_0010` entities."""
    log = DiagnosticLog()
    parsed("BL21I-DI-IOC-01", log)
    mismatches = [d for d in log if d.code == "slave-type-mismatch"]
    assert len(mismatches) == 5
    assert all(d.severity is Severity.WARNING for d in mismatches)
    assert not log.has_errors()


def test_unknown_entity_types_raise_nothing_while_parsing():
    """`auto_EL2595` / `auto_EL4134` only matter if something references them."""
    log = DiagnosticLog()
    chain = parsed("BL21I-DI-IOC-01", log)
    unknown = [s for s in chain.slaves if s.entity_type and not s.is_known]
    assert {s.entity_type for s in unknown} == {"auto_EL2595", "auto_EL4134"}
    assert "unknown-entity-type" not in codes(log)
    assert not log.has_errors()


def test_the_whole_bl21i_beamline_parses_without_a_single_error():
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log)
    assert [c.scanner_ioc for c in chains] == SCANNERS
    assert codes(log) == Counter(
        {
            "device-mod-mismatch": 32,
            "device-without-mod": 6,
            "unlabelled-coupler": 5,
            "slave-type-mismatch": 5,
            "duplicate-coupler-label": 1,
        }
    )
    assert not log.has_errors()


# -- ordinal allocation ------------------------------------------------------


def test_ordinals_are_allocated_per_domain_in_scanner_name_order():
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log)
    assert {c.scanner_ioc: c.ordinal for c in chains} == {
        "BL21I-DI-IOC-01": 1,
        "BL21I-VA-IOC-01": 1,
        "BL21I-VA-IOC-05": 2,
        "BL21I-VA-IOC-06": 3,
    }
    assert {c.scanner_ioc: c.node_prefix for c in chains}["BL21I-VA-IOC-06"] == (
        "BL21I-VA-E3RIO-{:02d}"
    )


def test_sticky_ordinals_are_honoured_and_never_renumbered():
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log, sticky={"BL21I-VA-CATIO-05": 3})
    allocated = {c.scanner_ioc: c.ordinal for c in chains}
    assert allocated["BL21I-VA-IOC-05"] == 3
    # the other two take the lowest ordinals still free, in name order
    assert allocated["BL21I-VA-IOC-01"] == 1
    assert allocated["BL21I-VA-IOC-06"] == 2
    assert allocated["BL21I-DI-IOC-01"] == 1


def test_sticky_ordinals_from_another_domain_do_not_leak():
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log, sticky={"BL21I-DI-CATIO-01": 4})
    allocated = {c.scanner_ioc: c.ordinal for c in chains}
    assert allocated["BL21I-DI-IOC-01"] == 4
    assert allocated["BL21I-VA-IOC-01"] == 1


def test_clashing_sticky_ordinals_are_a_value_error_not_a_diagnostic():
    log = DiagnosticLog()
    with pytest.raises(ValueError, match="pins ordinal 2 to both"):
        discover_chains(
            SAMPLES,
            log,
            sticky={"BL21I-VA-CATIO-01": 2, "BL21I-VA-CATIO-05": 2},
        )


def test_discover_chains_accepts_a_builder_root(tmp_path):
    make_iocs = tmp_path / "etc" / "makeIocs"
    make_iocs.mkdir(parents=True)
    for scanner in SCANNERS:
        (make_iocs / f"{scanner}.xml").write_text(
            (SAMPLES / f"{scanner}.xml").read_text()
        )
    log = DiagnosticLog()
    assert [c.scanner_ioc for c in discover_chains(tmp_path, log)] == SCANNERS


# -- the fastcs-catio boundary ----------------------------------------------


def test_predict_prefixes_names_the_side_venv_when_fastcs_is_absent():
    try:
        import fastcs_catio  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("fastcs_catio is installed, so the ImportError cannot fire")
    with pytest.raises(ImportError, match=r"\.venv-catio"):
        predict_prefixes(parsed("BL21I-VA-IOC-06"), DiagnosticLog())


# ============================================================================
# Everything below needs the real fastcs-catio naming API.
# ============================================================================


@pytest.fixture(scope="module")
def _fastcs():
    return pytest.importorskip(
        "fastcs_catio.naming",
        reason="run with .venv-catio/bin/python -m pytest",
    )


@pytest.fixture(scope="module")
def converted():
    """Every sample chain, with its substituter, built exactly as the CLI does."""
    pytest.importorskip("fastcs_catio.naming")
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log)
    substituter = build_substituter(chains, log)
    return chains, substituter, log


def test_local_locate_agrees_with_fastcs_catio(_fastcs):
    """The one guard against the duplicated bus walk drifting."""
    for scanner in SCANNERS:
        chain = parsed(scanner)
        entries = [_fastcs.ChainEntry(s.type_name, s.revision) for s in chain.slaves]
        theirs = _fastcs._locate(entries)
        ours = [(s.node, s.position, s.category) for s in chain.slaves]
        assert ours == theirs, scanner


def test_the_three_worked_examples(converted):
    _, substituter, _ = converted
    assert substituter.subs["BL21I-VA-ERIO-01:MOD1:INPUT1:VALUE"].read == (
        "BL21I-VA-E1RIO-05:10VAI01:AiStandardChannel1Value"
    )
    assert substituter.subs["BL21I-VA-ERIO-01:MOD5:CHANNEL1:INPUT"].read == (
        "BL21I-VA-E1RIO-05:24VDI01:Channel1"
    )
    assert substituter.subs["BL21I-VA-ERIO-04:MOD1:INPUT1:VALUE"].read == (
        "BL21I-VA-E1RIO-01:10VAI01:AiStandardChannel1Value"
    )


def test_the_dual_key_map_makes_the_mod1_restart_harmless(converted):
    """Declared `MOD1` and chain-derived `MOD5` land on the same terminal."""
    _, substituter, _ = converted
    declared = substituter.subs["BL21I-VA-ERIO-04:MOD1:CHANNEL1:INPUT"]
    derived = substituter.subs["BL21I-VA-ERIO-04:MOD5:CHANNEL1:INPUT"]
    assert declared == derived
    assert declared.read == "BL21I-VA-E1RIO-01:24VDI01:Channel1"
    # and the EL3104 that also declares MOD1 is disambiguated by its leaf
    assert substituter.subs["BL21I-VA-ERIO-04:MOD1:INPUT1:VALUE"].read.endswith(
        "10VAI01:AiStandardChannel1Value"
    )


def test_a_declared_name_beats_a_colliding_chain_derived_alias(converted):
    """`ERIO-01:MOD10` is declared at bus position 14 and derived at 10."""
    chains, substituter, _ = converted
    di = next(c for c in chains if c.scanner_ioc == "BL21I-DI-IOC-01")
    declared_at = next(
        s for s in di.slaves if s.declared_device == "BL21I-DI-ERIO-01:MOD10"
    )
    assert (declared_at.node, declared_at.position) == (8, 14)
    prefixes = predict_prefixes(di, DiagnosticLog())
    assert substituter.subs["BL21I-DI-ERIO-01:MOD10:CHANNEL1:OUTPUT"].write == (
        f"{prefixes[(8, 14)]}:Channel1"
    )
    assert "BL21I-DI-ERIO-01:MOD10:CHANNEL1:OUTPUT" not in substituter.unresolved


def test_modsam_names_resolve_because_declared_names_are_opaque(converted):
    _, substituter, _ = converted
    for n in range(3, 8):
        key = f"BL21I-DI-ERIO-05:MODSAM{n}:CHANNEL1:OUTPUT"
        assert substituter.subs[key].write.endswith(":Channel1")


def test_el2024_0010_is_read_write_so_readers_get_the_rbv(converted):
    _, substituter, _ = converted
    rw = substituter.subs["BL21I-DI-ERIO-09:MOD1:CHANNEL1:OUTPUT"]
    assert rw.writable
    assert rw.read == rw.write + "_RBV"
    # a read-only EL1014 leaf has one name for both directions
    ro = substituter.subs["BL21I-VA-ERIO-04:MOD5:CHANNEL1:INPUT"]
    assert not ro.writable


def test_unmapped_suffixes_are_registered_as_unresolved(converted):
    _, substituter, _ = converted
    entry = substituter.unresolved["BL21I-VA-ERIO-04:MOD3:AL_STATE"]
    assert entry[0] == "unmapped-suffix"
    assert entry[2] == "BL21I-VA-IOC-01"


def test_unknown_entity_types_resolve_by_prefix(converted):
    _, substituter, _ = converted
    code, _, chain = substituter.unresolved.get("BL21I-DI-LED-01:CHANNEL1:OUTPUT")
    assert code == "unknown-entity-type"
    assert chain == "BL21I-DI-IOC-01"


def test_no_leaf_is_shortened_at_the_emitted_prefixes(converted):
    chains, _, _ = converted
    for chain in chains:
        log = DiagnosticLog()
        predict_prefixes(chain, log)
        assert [d for d in log if d.code == "shortened-leaf"] == []


def test_the_shortening_guard_fires_for_a_four_segment_node_prefix(monkeypatch):
    """fastcs-catio's *default* node_prefix truncates the channel out of a leaf."""
    pytest.importorskip("fastcs_catio.naming")
    chain = parsed("BL21I-VA-IOC-01")
    monkeypatch.setattr(
        Chain, "node_prefix", property(lambda self: "{device_prefix}:E1RIO{:02d}")
    )
    log = DiagnosticLog()
    predict_prefixes(chain, log)
    shortened = [d for d in log if d.code == "shortened-leaf"]
    assert shortened
    assert all(d.severity is Severity.ERROR for d in shortened)
    assert "ai_standard_channel_1_value" in shortened[0].message
    assert log.failed_chains() == {"BL21I-VA-IOC-01"}


def test_unknown_terminal_types_fail_the_chain(tmp_path):
    pytest.importorskip("fastcs_catio.naming")
    xml = tmp_path / "BL99Z-XX-IOC-01.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n'
        '<components arch="linux-x86_64">\n'
        '<ethercat.EthercatMaster name="ECATM" socket="/tmp/socket0"/>\n'
        '<ethercat.EthercatSlave master="ECATM" name="C1" type_rev="EK1100 rev 0x1"/>\n'
        '<ethercat.EthercatSlave master="ECATM" name="T1" type_rev="EL9999 rev 0x1"/>\n'
        "</components>\n"
    )
    log = DiagnosticLog()
    chain = parse_chain(xml, log, ordinal=1)
    assert chain is not None
    assert predict_prefixes(chain, log) == {}
    assert [d.code for d in log] == ["unlabelled-coupler", "unknown-terminal-type"]
    assert log.failed_chains() == {"BL99Z-XX-IOC-01"}


def test_every_consumer_reference_on_bl21i_rewrites_cleanly(
    converted, expected_references
):
    """The end-to-end contract: 177 real references, no errors, no chain lost."""
    _, substituter, log = converted
    changed = 0
    for row in expected_references:
        if row["entity_type"].startswith("ethercat.auto_"):
            continue  # the declarations themselves, deleted rather than rewritten
        after = substituter.rewrite_value(
            row["value"],
            attribute=row["attribute"],
            log=log,
            ioc=row["ioc"],
            entity=row["entity_name"],
        )
        assert after != row["value"], row
        changed += 1
    assert changed == 177
    assert report_unused_ambiguities(substituter, log) == []
    assert log.errors == []
    assert log.failed_chains() == set()
    # VA-IOC-06's only reference row is its own auto_EL3104 declaration, which
    # is skipped above -- the entity is deleted by the converter, not rewritten.
    assert substituter.touched_iocs() == {
        "BL21I-DI-IOC-01",
        "BL21I-VA-IOC-01",
        "BL21I-VA-IOC-02",
        "BL21I-VA-IOC-04",
        "BL21I-VA-IOC-05",
    }


def test_a_failed_chain_contributes_no_substitutions():
    pytest.importorskip("fastcs_catio.naming")
    log = DiagnosticLog(strict=True)  # promotes device-mod-mismatch to ERROR
    chains = discover_chains(SAMPLES, log)
    assert log.failed_chains() == {"BL21I-DI-IOC-01", "BL21I-VA-IOC-01"}
    substituter = build_substituter(chains, log)
    assert set(substituter.owners.values()) == {
        "BL21I-VA-IOC-05",
        "BL21I-VA-IOC-06",
    }
    assert "BL21I-VA-ERIO-01:MOD1:INPUT1:VALUE" not in substituter.subs


def test_report_unused_ambiguities_downgrades_only_untouched_ones():
    pytest.importorskip("fastcs_catio.naming")
    log = DiagnosticLog()
    chains = discover_chains(SAMPLES, log)
    substituter = build_substituter(chains, log)
    # inject an ambiguity nothing references, and one that is referenced
    for key in ("BL21I-VA-ERIO-01:MOD9:GHOST", "BL21I-VA-ERIO-01:MOD8:SEEN"):
        substituter.unresolved[key] = (
            "ambiguous-legacy-pv",
            f"{key} maps to more than one fastcs-catio PV",
            "BL21I-VA-IOC-01",
        )
    substituter.rewrite_value(
        "BL21I-VA-ERIO-01:MOD8:SEEN",
        attribute="INP",
        log=log,
        ioc="BL21I-VA-IOC-04",
        entity="thing",
    )
    assert report_unused_ambiguities(substituter, log) == [
        "BL21I-VA-ERIO-01:MOD9:GHOST"
    ]
    assert codes(log)["ambiguous-legacy-pv"] == 1
    assert codes(log)["ambiguous-legacy-pv-unused"] == 1


def test_slave_dataclass_is_hashable_and_frozen():
    slave = Slave(1, 1, "EL3104", 1, "P", "slave", "auto_EL3104")
    assert hash(slave)
    with pytest.raises(AttributeError):
        slave.position = 2  # type: ignore[misc]
