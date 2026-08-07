"""Regression tests for defects found by adversarial review of `catio`.

One test per defect, each named after what went wrong. They are kept together
rather than folded into the per-module files so that the guarantees bought by
each fix stay legible as a set: every one of these is a way the tool used to
emit, or silently keep, a PV reference pointing at a record no IOC creates.

The chains here are written out in full rather than derived from
``tests/samples/catio/``: each defect needs a topology the real BL21I XMLs do
not contain (or contain only by luck), and a fixture that drifts with the
samples would stop testing the defect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

# Ahead of the builder2ibek.catio imports: those reach fastcs_catio lazily today,
# but if one ever grows a module-scope import this file must skip rather than
# fail collection.
fastcs_catio = pytest.importorskip("fastcs_catio")

from builder2ibek.catio.chains import (  # noqa: E402
    build_substituter,
    discover_chains,
)
from builder2ibek.catio.cli import catio_cli  # noqa: E402
from builder2ibek.catio.diagnostics import DiagnosticLog, Severity  # noqa: E402
from builder2ibek.catio.substitute import NewPv, Substituter  # noqa: E402
from builder2ibek.convert import convert_to_ioc  # noqa: E402
from builder2ibek.converters.ethercat import CatioContext  # noqa: E402


def write_chain(directory: Path, ioc: str, body: str) -> Path:
    """Write one builder XML holding *body* between the ``components`` tags."""
    directory.mkdir(parents=True, exist_ok=True)
    xml = directory / f"{ioc}.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n'
        '<components arch="linux-x86_64">\n'
        f"{body}\n"
        "</components>\n"
    )
    return xml


MASTER = '\t<ethercat.EthercatMaster name="ECATM" socket="/tmp/socket0"/>'


def slave(name: str, type_rev: str) -> str:
    return (
        f'\t<ethercat.EthercatSlave master="ECATM" name="{name}" '
        f'position="{name}" type_rev="{type_rev}"/>'
    )


def built(tmp_path: Path, ioc: str, body: str) -> tuple[Substituter, DiagnosticLog]:
    """Discover and build a substituter from a single one-chain XML."""
    write_chain(tmp_path, ioc, body)
    log = DiagnosticLog()
    return build_substituter(discover_chains(tmp_path, log), log), log


# -- 1: a declared DEVICE= without a ':MOD' part ------------------------------

# `BL21I-OP-LED-01`, `BL21I-MO-PIEZO-01` and `BL21I-DI-LED-0*` are all real
# BL21I terminals named after the device they drive rather than their bus slot.
# The declared-key family used to be gated on the `LABEL:MODn` shape, so their
# PVs -- the ones the legacy IOC really created -- were never registered, and
# `LEGACY_PV_RE` cannot catch the leftovers because they carry no `-ERIO-`.
DEVICE_CHAIN = "\n".join(
    [
        MASTER,
        slave("S0", "EK1100 rev 0x00120000"),
        slave("S1", "EL1014 rev 0x00120000"),
        slave("S2", "EL2024-0010 rev 0x0012000a"),
        '\t<ethercat.auto_EL1014 DEVICE="BL21I-VA-ERIO-01:MOD1" PORT="S1" name="E1"/>',
        '\t<ethercat.auto_EL2024_0010 DEVICE="BL21I-OP-LED-01" PORT="S2" name="E2"/>',
    ]
)


def test_device_without_mod_still_registers_its_declared_pvs(tmp_path):
    sub, log = built(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)

    assert sub.subs["BL21I-OP-LED-01:CHANNEL1:OUTPUT"].write == (
        "BL21I-VA-E1RIO-01:12VDO01:Channel1"
    )
    # and the chain-derived alias still resolves to the same terminal
    assert (
        sub.subs["BL21I-VA-ERIO-01:MOD2:CHANNEL1:OUTPUT"]
        == sub.subs["BL21I-OP-LED-01:CHANNEL1:OUTPUT"]
    )
    # ignoring it for *label derivation* is still right, and still reported
    assert [d.code for d in log if d.code == "device-without-mod"] == [
        "device-without-mod"
    ]


def test_device_without_mod_reference_is_rewritten_not_passed_through(tmp_path):
    sub, log = built(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)

    rewritten = sub.rewrite_value(
        "BL21I-OP-LED-01:CHANNEL1:OUTPUT PP",
        attribute="OUTGB0",
        log=log,
        ioc="BL21I-OP-IOC-01",
        entity="femto",
    )
    assert rewritten == "BL21I-VA-E1RIO-01:12VDO01:Channel1 PP"
    assert sub.touched_iocs() == {"BL21I-OP-IOC-01"}


# -- 2: an orphaned sticky ordinal ---------------------------------------------


def test_a_sticky_pin_with_no_scanner_still_reserves_its_ordinal(tmp_path):
    """A deployed catio IOC owns its E{n}RIO names whether or not its XML lives.

    Its scanner XML being renamed or retired must not hand ordinal 1 to a live
    chain in the same domain: two IOCs would then serve identical PV names.
    """
    write_chain(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)
    log = DiagnosticLog()

    chains = discover_chains(tmp_path, log, sticky={"BL21I-VA-CATIO-09": 1})

    assert [(c.scanner_ioc, c.ordinal) for c in chains] == [("BL21I-VA-IOC-01", 2)]
    assert chains[0].node_prefix == "BL21I-VA-E2RIO-{:02d}"


def test_an_orphan_pin_in_another_domain_reserves_nothing(tmp_path):
    write_chain(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)
    log = DiagnosticLog()

    chains = discover_chains(tmp_path, log, sticky={"BL21I-DI-CATIO-09": 1})

    assert chains[0].ordinal == 1


def test_two_pins_on_one_ordinal_are_a_corrupt_repo_even_when_orphaned(tmp_path):
    write_chain(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)
    log = DiagnosticLog()

    with pytest.raises(ValueError, match="pins ordinal 1 to both"):
        discover_chains(
            tmp_path,
            log,
            sticky={"BL21I-VA-CATIO-08": 1, "BL21I-VA-CATIO-09": 1},
        )


# -- 3 and 4: a chain that fails before substitution ---------------------------

# EL9999 is in no `terminal_types.yaml`, so this chain fails inside
# `predict_prefixes` -- before it can contribute a single key. Its terminals'
# names must still be recognised, or a consumer straddling it is written with
# the reference left dangling and nothing in the report says so.
FAILED_CHAIN = "\n".join(
    [
        MASTER,
        slave("C1", "EK1100 rev 0x00120000"),
        slave("T1", "EL2024-0010 rev 0x00120000"),
        '\t<ethercat.auto_EL2024_0010 DEVICE="BL21I-DI-ERIO-01:MOD1" PORT="T1"'
        ' name="DIG1"/>',
        slave("T2", "EL2024-0010 rev 0x00120000"),
        '\t<ethercat.auto_EL2024_0010 DEVICE="BL21I-DI-LED-01" PORT="T2" name="LED1"/>',
        slave("T3", "EL9999 rev 0x00120000"),
    ]
)


@pytest.fixture
def straddled(tmp_path) -> tuple[Substituter, DiagnosticLog]:
    """One failed chain and one clean one, both in the same tree."""
    write_chain(tmp_path, "BL21I-DI-IOC-01", FAILED_CHAIN)
    write_chain(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)
    log = DiagnosticLog()
    return build_substituter(discover_chains(tmp_path, log), log), log


def test_a_failed_chain_still_fails_loudly(straddled):
    sub, log = straddled
    assert "BL21I-DI-IOC-01" in log.failed_chains()
    assert sub.subs, "the clean chain must still contribute its keys"


@pytest.mark.parametrize(
    "token",
    [
        # a declared DEVICE= with no `-ERIO-` segment: LEGACY_PV_RE cannot see it
        "BL21I-DI-LED-01:CHANNEL1:OUTPUT",
        # and one reached through the failed chain's coupler label
        "BL21I-DI-ERIO-01:MOD1:CHANNEL1:OUTPUT",
    ],
)
def test_a_reference_into_a_failed_chain_errors_and_names_that_chain(straddled, token):
    sub, log = straddled

    value = sub.rewrite_value(
        f"{token} PP",
        attribute="OUT",
        log=log,
        ioc="BL21I-DI-IOC-02",
        entity="G1",
    )

    assert value == f"{token} PP", "an unresolvable reference is left alone"
    raised = [d for d in log if d.ioc == "BL21I-DI-IOC-02"]
    assert [d.severity for d in raised] == [Severity.ERROR]
    # named, so the report can say which chain has to be fixed
    assert raised[0].chain == "BL21I-DI-IOC-01"
    assert sub.references("BL21I-DI-IOC-02") == {"BL21I-DI-IOC-01"}


def test_a_clean_chain_is_never_shadowed_by_a_failed_one(straddled):
    """The failed chain's prefixes must not swallow a converted chain's keys."""
    sub, log = straddled

    value = sub.rewrite_value(
        "BL21I-VA-ERIO-01:MOD1:CHANNEL1:INPUT CP",
        attribute="INP",
        log=log,
        ioc="BL21I-DI-IOC-02",
        entity="G2",
    )

    assert value == "BL21I-VA-E1RIO-01:24VDI01:Channel1 CP"
    assert [d for d in log if d.ioc == "BL21I-DI-IOC-02"] == []
    assert sub.references("BL21I-DI-IOC-02") == {"BL21I-VA-IOC-01"}


# -- 5: leaf-type-mismatch ------------------------------------------------------

# The entity type decides which leaf table is used, but fastcs-catio builds its
# attributes from the *slave's own* type. Where the two disagree the predicted
# name -- or its `_RBV` suffix -- is for a PV that will not exist.
MISBOUND = "\n".join(
    [
        MASTER,
        slave("S0", "EK1100 rev 0x00120000"),
        slave("S1", "EL1014 rev 0x00120000"),
        slave("S2", "EL2024-0010 rev 0x0012000a"),
        # an EL3104 table on an EL1014: the attribute does not exist at all
        '\t<ethercat.auto_EL3104 DEVICE="BL21I-VA-ERIO-01:MOD1" PORT="S1" name="E1"/>',
        # an EL1014 table on an EL2024-0010: `channel_n` exists but is R/W
        '\t<ethercat.auto_EL1014 DEVICE="BL21I-VA-ERIO-01:MOD2" PORT="S2" name="E2"/>',
    ]
)


def test_a_leaf_absent_from_the_real_terminal_is_an_error(tmp_path):
    _, log = built(tmp_path, "BL21I-VA-IOC-01", MISBOUND)

    absent = [d for d in log if d.code == "leaf-type-mismatch" and d.entity == "E1"]
    assert absent, "auto_EL3104 leaves do not exist on an EL1014"
    assert all(d.severity is Severity.ERROR for d in absent)
    assert "ai_standard_channel_1_value" in " ".join(d.message for d in absent)


def test_a_writability_disagreement_is_an_error(tmp_path):
    _, log = built(tmp_path, "BL21I-VA-IOC-01", MISBOUND)

    mismatched = [d for d in log if d.code == "leaf-type-mismatch" and d.entity == "E2"]
    assert len(mismatched) == 4, "one per channel"
    assert "_RBV" in mismatched[0].message


def test_a_correctly_bound_chain_raises_no_leaf_type_mismatch(tmp_path):
    _, log = built(tmp_path, "BL21I-VA-IOC-01", DEVICE_CHAIN)

    assert [d for d in log if d.code == "leaf-type-mismatch"] == []


def test_el2024_bound_to_the_0010_table_is_not_a_leaf_type_mismatch(tmp_path):
    """The one real BL21I `slave-type-mismatch`, and it is harmless.

    Five DI terminals are plain `EL2024` bound to `auto_EL2024_0010`. Both
    types give fastcs-catio the same four read/write `channel_n` attributes, so
    only the module prefix differs -- and that is predicted from the slave's own
    type. Promoting this to an error would fail a chain for nothing.
    """
    body = "\n".join(
        [
            MASTER,
            slave("S0", "EK1100 rev 0x00120000"),
            slave("S1", "EL2024 rev 0x00120000"),
            '\t<ethercat.auto_EL2024_0010 DEVICE="BL21I-DI-ERIO-01:MOD1" PORT="S1"'
            ' name="E1"/>',
        ]
    )
    sub, log = built(tmp_path, "BL21I-DI-IOC-01", body)

    assert [d.code for d in log] == ["slave-type-mismatch"]
    assert not log.has_errors()
    assert sub.subs["BL21I-DI-ERIO-01:MOD1:CHANNEL1:OUTPUT"].write == (
        "BL21I-DI-E1RIO-01:24VDO01:Channel1"
    )


# -- 3, end to end: the straddling consumer must not be written ----------------


@pytest.fixture
def services_repo(tmp_path: Path) -> Path:
    """A minimal services repo: the shared chart plus the two scaffolds."""
    repo = tmp_path / "services-repo"
    shared = repo / ".helm-shared"
    (shared / "templates").mkdir(parents=True)
    (shared / "Chart.yaml").write_text("apiVersion: v2\nname: ec-service\n")
    (shared / "templates" / "ioc_instance.yaml").write_text("{}\n")
    for name in (".ioc_template", ".fastcs_ioc_template"):
        folder = repo / "services" / name
        (folder / "config").mkdir(parents=True)
        (folder / "values.yaml").write_text(
            "ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n"
        )
        (folder / "config" / "ioc.yaml").write_text(
            "description: REPLACE_WITH_DESCRIPTION\nentities: []\n"
        )
        (folder / "Chart.yaml").symlink_to("../../.helm-shared/Chart.yaml")
        (folder / "templates").symlink_to("../../.helm-shared/templates")
    return repo


#: References one PV from each chain. The DI one is a declared `DEVICE=` with
#: no `-ERIO-` segment, which is exactly what used to slip through unnoticed.
STRADDLING_CONSUMER = "\n".join(
    [
        '\t<mks9xx.mks9xxGauge P="BL21I-VA-GAUGE-01" id="1" name="G1"'
        ' plog_adc_pv="BL21I-DI-LED-01:CHANNEL1:OUTPUT"/>',
        '\t<mks9xx.mks9xxGauge P="BL21I-VA-GAUGE-02" id="2" name="G2"'
        ' plog_adc_pv="BL21I-VA-ERIO-01:MOD1:CHANNEL1:INPUT"/>',
    ]
)


@pytest.fixture
def straddling_tree(tmp_path: Path) -> Path:
    root = tmp_path / "BL21I-BUILDER"
    make_iocs = root / "etc" / "makeIocs"
    write_chain(make_iocs, "BL21I-DI-IOC-01", FAILED_CHAIN)
    write_chain(make_iocs, "BL21I-VA-IOC-01", DEVICE_CHAIN)
    write_chain(make_iocs, "BL21I-DI-IOC-02", STRADDLING_CONSUMER)
    return root


def run_catio(builder_path: Path, services_repo: Path, **kwargs) -> int:
    try:
        catio_cli(builder_path, services_repo, **kwargs)
    except typer.Exit as exc:
        return int(exc.exit_code)
    return 0


def test_an_ioc_straddling_a_build_time_failure_is_skipped_whole(
    straddling_tree: Path, services_repo: Path, capsys
):
    """Half-rewritten is worse than unconverted, and the report must say why.

    The DI chain dies inside ``predict_prefixes`` -- before it contributes a
    single key -- so it used to leave no trace the consumer's reference could
    hit. The consumer was written with the DI PV untouched, no diagnostic, and
    no mention in the report.
    """
    code = run_catio(straddling_tree, services_repo, json_out=True)
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["iocs_written"] == ["BL21I-VA-IOC-01"]
    skipped = {item["ioc"]: item for item in payload["iocs_skipped"]}
    assert skipped["BL21I-DI-IOC-02"]["blocked_by"] == ["BL21I-DI-IOC-01"]
    assert not (services_repo / "services" / "bl21i-di-ioc-02").exists()


# -- 6: a reference inside an entity the conversion drops ----------------------

# `records.*` has no ibek equivalent and is deleted outright, taking any
# EtherCAT reference inside it with it. Two real BL21I IOCs
# (BL21I-MO-IOC-02, -06) depend on a chain solely through a `records.calcout`,
# and used to appear in no section of the report at all.
DROPPING_CONSUMER = "\n".join(
    [
        '\t<records.calcout name="C1" CALC="A"'
        ' OUT="BL21I-VA-ERIO-01:MOD1:CHANNEL1:INPUT NPP MS"/>',
    ]
)


def converted(tmp_path: Path, body: str, sub: Substituter, log: DiagnosticLog):
    xml = write_chain(tmp_path / "consumer", "BL21I-VA-IOC-02", body)
    return convert_to_ioc(
        xml, catio=CatioContext(substituter=sub, log=log, ioc_name="BL21I-VA-IOC-02")
    )


def test_a_reference_lost_with_a_dropped_entity_is_reported(tmp_path: Path):
    sub, log = built(tmp_path / "chain", "BL21I-VA-IOC-01", DEVICE_CHAIN)

    ioc = converted(tmp_path, DROPPING_CONSUMER, sub, log)

    assert "calcout" not in str(ioc.entities), "the entity really is dropped"
    dropped = [d for d in log if d.code == "dropped-reference"]
    assert len(dropped) == 1
    assert dropped[0].severity is Severity.WARNING
    assert dropped[0].ioc == "BL21I-VA-IOC-02"
    assert dropped[0].attribute == "OUT"
    assert dropped[0].chain == "BL21I-VA-IOC-01"
    assert "BL21I-VA-ERIO-01:MOD1:CHANNEL1:INPUT" in dropped[0].message


def test_a_reference_that_survived_conversion_is_not_reported_as_dropped(
    tmp_path: Path,
):
    sub, log = built(tmp_path / "chain", "BL21I-VA-IOC-01", DEVICE_CHAIN)

    ioc = converted(tmp_path, STRADDLING_CONSUMER, sub, log)

    assert [d for d in log if d.code == "dropped-reference"] == []
    assert "BL21I-VA-E1RIO-01:24VDI01:Channel1" in str(ioc.entities)


def test_the_scanners_own_ethercat_entities_are_not_reported_as_dropped(
    tmp_path: Path,
):
    """Their replacement is the generated catio IOC, not a hand-written record."""
    sub, log = built(tmp_path / "chain", "BL21I-VA-IOC-01", DEVICE_CHAIN)
    xml = tmp_path / "chain" / "BL21I-VA-IOC-01.xml"

    convert_to_ioc(
        xml, catio=CatioContext(substituter=sub, log=log, ioc_name="BL21I-VA-IOC-01")
    )

    assert [d for d in log if d.code == "dropped-reference"] == []


def test_a_second_pv_in_the_value_does_not_decide_the_first_ones_direction():
    """A writer followed by a reader must not be pulled onto the readback.

    `_trailing_flags` used to join every token after the PV, so in
    "PV1 PP PV2 CP" the reader's `CP` reached PV1 and rewrote a writable
    output link to its read-only `_RBV` -- a PV the IOC cannot write.
    """
    writer = NewPv(read="NEW:A_RBV", write="NEW:A")
    reader = NewPv(read="NEW:B_RBV", write="NEW:B")
    sub = Substituter(
        {"OLD:A": writer, "OLD:B": reader},
        owners={"OLD:A": "SCANNER", "OLD:B": "SCANNER"},
        unresolved={},
        known_labels={},
    )
    log = DiagnosticLog()

    out = sub.rewrite_value(
        "OLD:A PP OLD:B CP", attribute="OUTGB0", log=log, ioc="IOC", entity="E"
    )

    assert out == "NEW:A PP NEW:B_RBV CP"


def test_a_lone_pv_still_sees_its_own_flags():
    """The companion check: the scan must not stop too early either."""
    reader = NewPv(read="NEW:B_RBV", write="NEW:B")
    sub = Substituter(
        {"OLD:B": reader},
        owners={"OLD:B": "SCANNER"},
        unresolved={},
        known_labels={},
    )
    log = DiagnosticLog()

    out = sub.rewrite_value(
        "OLD:B CP MS", attribute="whatever", log=log, ioc="IOC", entity="E"
    )

    assert out == "NEW:B_RBV CP MS"
