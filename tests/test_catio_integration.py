"""End-to-end tests for ``builder2ibek catio`` over the checked-in samples.

These drive the whole pipeline -- discover chains, predict fastcs-catio names,
rewrite every consumer, write the services repo -- against
``tests/samples/catio/``, which is a byte-identical copy of the four BL21I
EtherCAT scanner XMLs and two of their consumers.

The counts asserted here are checked in on purpose: a regression in the naming
rule, the dual-key substitution map or the per-chain failure policy shows up as
a number change rather than as a silent behavioural drift.

The whole module needs the real ``fastcs_catio`` naming API, which is
deliberately absent from the project venv, so it self-skips under plain
``uv run``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer

pytest.importorskip("fastcs_catio")

from builder2ibek.catio.chains import (  # noqa: E402
    build_substituter,
    discover_chains,
)
from builder2ibek.catio.cli import catio_cli  # noqa: E402
from builder2ibek.catio.diagnostics import DiagnosticLog  # noqa: E402

CATIO_SAMPLES = Path(__file__).parent / "samples" / "catio"

#: The scanner IOCs, and the ``E{n}RIO`` ordinal each must be allocated.
#: Ordinals are per ``(beamline, domain)`` in ascending scanner-IOC name order.
EXPECTED_ORDINALS = {
    "BL21I-DI-CATIO-01": 1,
    "BL21I-VA-CATIO-01": 1,
    "BL21I-VA-CATIO-05": 2,
    "BL21I-VA-CATIO-06": 3,
}

#: Every BL21I chain converts. ``BL21I-DI-IOC-01`` was the last holdout: it
#: needed ``auto_EL2595`` and ``auto_EL4134`` leaf tables, and the EL2595 drive
#: current had to be selected in fastcs-catio's ``terminal_types.yaml``
#: (fastcs-catio#65) before there was a PV to point its four ``dbpf`` writes at.
#:
#: Nothing in the samples exercises the per-chain failure policy any more.
#: That is covered on purpose by synthetic chains in
#: ``tests/test_catio_regressions.py`` -- a failed chain failing loudly, a
#: reference into one erroring, a clean chain not being shadowed by it, and a
#: straddling consumer being skipped whole -- so the coverage does not depend on
#: a real beamline staying broken.
EXPECTED_FAILED_CHAINS: set[str] = set()

#: Consumers of a chain, so they are rewritten and written out.
EXPECTED_IOCS_WRITTEN = {
    "BL21I-DI-IOC-01",
    "BL21I-VA-IOC-01",
    "BL21I-VA-IOC-02",
    "BL21I-VA-IOC-04",
    "BL21I-VA-IOC-05",
    "BL21I-VA-IOC-06",
}


@pytest.fixture
def builder_tree(tmp_path: Path) -> Path:
    """A BUILDER support module holding just the sampled XMLs."""
    make_iocs = tmp_path / "BL21I-BUILDER" / "etc" / "makeIocs"
    make_iocs.mkdir(parents=True)
    for xml in sorted(CATIO_SAMPLES.glob("*.xml")):
        shutil.copy(xml, make_iocs / xml.name)
    return tmp_path / "BL21I-BUILDER"


@pytest.fixture
def services_repo(tmp_path: Path) -> Path:
    """A minimal services repo: the shared chart plus the two scaffolds."""
    repo = tmp_path / "i21-services"
    shared = repo / ".helm-shared"
    (shared / "templates").mkdir(parents=True)
    (shared / "Chart.yaml").write_text("apiVersion: v2\nname: ec-service\n")
    (shared / "templates" / "ioc_instance.yaml").write_text(
        '{{ include "ioc-instance" . }}\n'
    )
    for name, values in (
        (".ioc_template", "ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n"),
        (
            ".fastcs_ioc_template",
            "ioc-instance:\n  image: REPLACE_WITH_FASTCS_IMAGE_URI\n",
        ),
    ):
        folder = repo / "services" / name
        (folder / "config").mkdir(parents=True)
        (folder / "values.yaml").write_text(values)
        (folder / "config" / "ioc.yaml").write_text(
            "description: REPLACE_WITH_DESCRIPTION\nentities: []\n"
        )
        (folder / "Chart.yaml").symlink_to("../../.helm-shared/Chart.yaml")
        (folder / "templates").symlink_to("../../.helm-shared/templates")
    return repo


def run_catio(builder_path: Path, services_repo: Path, **kwargs) -> int:
    """Call :func:`catio_cli` and return its exit code rather than raising."""
    try:
        catio_cli(builder_path, services_repo, **kwargs)
    except typer.Exit as exc:
        return int(exc.exit_code)
    return 0


def folders(services_repo: Path) -> set[str]:
    """Every non-scaffold service folder name in *services_repo*."""
    return {
        child.name
        for child in (services_repo / "services").iterdir()
        if child.is_dir() and not child.name.startswith(".")
    }


# -- the full run ------------------------------------------------------------


def test_full_run_writes_exactly_the_expected_folders(
    builder_tree: Path, services_repo: Path, capsys
):
    """One fastcs-catio folder per clean chain, plus every rewritten consumer."""
    code = run_catio(builder_tree, services_repo)
    capsys.readouterr()

    # Zero: every chain converts, so no error fired.
    assert code == 0

    expected = {name.lower() for name in EXPECTED_IOCS_WRITTEN} | {
        "bl21i-di-catio-01",
        "bl21i-va-catio-01",
        "bl21i-va-catio-05",
        "bl21i-va-catio-06",
    }
    assert folders(services_repo) == expected

    # Every chain got both a fastcs-catio IOC and a rewritten scanner.
    assert (services_repo / "services" / "bl21i-di-catio-01").is_dir()
    assert (services_repo / "services" / "bl21i-di-ioc-01").is_dir()


def test_the_whole_beamline_converts_with_no_chain_blocked(
    builder_tree: Path, services_repo: Path, capsys
):
    """Every BL21I chain converts, so nothing is skipped and no error fires.

    This is the guard on the leaf tables: dropping ``auto_EL2595`` or
    ``auto_EL4134``, or fastcs-catio deselecting the EL2595 drive current again,
    puts ``BL21I-DI-IOC-01`` straight back into ``iocs_skipped``.
    """
    run_catio(builder_tree, services_repo, json_out=True)
    report = json.loads(capsys.readouterr().out)

    failed = {c["scanner_ioc"] for c in report["chains"] if not c["converted"]}
    assert failed == EXPECTED_FAILED_CHAINS

    assert [d for d in report["diagnostics"] if d["severity"] == "error"] == []
    assert report["iocs_skipped"] == []

    # The four LED drive currents are dbpf *writes*, so they must land on the
    # setpoint and never on the read-only `_RBV`.
    written = [d for d in report["diagnostics"] if d["code"] == "link-direction-guess"]
    assert written == [], "no writable leaf should be left to a guess"


def test_no_written_ioc_still_references_a_legacy_ethercat_pv(
    builder_tree: Path, services_repo: Path, capsys
):
    """The point of the exercise: every legacy ``:MOD<n>:`` reference is gone."""
    run_catio(builder_tree, services_repo)
    capsys.readouterr()

    for name in EXPECTED_IOCS_WRITTEN:
        text = (
            services_repo / "services" / name.lower() / "config" / "ioc.yaml"
        ).read_text()
        assert "-ERIO-" not in text, f"{name} still names a legacy coupler label"


# -- reference coverage ------------------------------------------------------

#: Of the 247 sampled references, 70 are the ``ethercat.auto_*`` ``DEVICE=``
#: declarations themselves. Those entities are deleted by the converter, so
#: there is nothing to rewrite; the remaining 177 are real consumer references
#: and every one of them must be rewritten by the substitution map.
EXPECTED_DECLARATIONS = 70
EXPECTED_REWRITTEN = 177
EXPECTED_DIAGNOSED = 0


def test_every_sampled_reference_is_rewritten_or_diagnosed(builder_tree: Path):
    """No reference may be silently left pointing at a record that will not exist.

    Built over *all four* chains -- including the one the CLI skips -- because
    this asserts the substitution map's coverage, not the failure policy.
    """
    references = json.loads((CATIO_SAMPLES / "expected_references.json").read_text())
    assert len(references) == 247

    log = DiagnosticLog()
    substituter = build_substituter(discover_chains(builder_tree, log), log)

    rewritten = declarations = diagnosed = 0
    unaccounted: list[str] = []
    for ref in references:
        entity_type, attribute = ref["entity_type"], ref["attribute"]
        if entity_type.startswith("ethercat.auto_") and attribute == "DEVICE":
            declarations += 1
            continue
        ref_log = DiagnosticLog()
        new = substituter.rewrite_value(
            ref["value"],
            attribute=attribute,
            log=ref_log,
            ioc=ref["ioc"],
            entity=ref["entity_name"],
        )
        if new != ref["value"]:
            rewritten += 1
        elif len(ref_log):
            diagnosed += 1
        else:
            unaccounted.append(f"{ref['ioc']} {ref['entity_name']}.{attribute}")

    assert unaccounted == []
    assert declarations == EXPECTED_DECLARATIONS
    assert rewritten == EXPECTED_REWRITTEN
    assert diagnosed == EXPECTED_DIAGNOSED
    assert declarations + rewritten + diagnosed == len(references)


#: Substitution-map size over all four chains. Pinned so a change in the naming
#: rule or the dual-key policy cannot pass unnoticed.
#:
#: Rose from 526 by 19 when the ``auto_EL2595`` and ``auto_EL4134`` tables were
#: added: 7 for EL2595 (4 terminals x 1 leaf, declared, plus 3 chain-derived)
#: and 12 for EL4134 (2 terminals x 4 leaves, declared, plus 4 chain-derived).
#: Fewer chain-derived aliases than declared keys because an alias needs a
#: coupler label, and several ``BL21I-DI`` couplers have none -- every entity on
#: them declares a device-style ``DEVICE=`` with no ``:MOD`` part, so there is
#: nothing to derive a label from. None of the shortfall is a dropped collision.
EXPECTED_SUBSTITUTIONS = 545


def test_substitution_map_size_is_stable(builder_tree: Path):
    log = DiagnosticLog()
    substituter = build_substituter(discover_chains(builder_tree, log), log)
    assert len(substituter.subs) == EXPECTED_SUBSTITUTIONS
    # Every unresolved entry carries a code, so nothing drops out unexplained.
    assert all(entry[0] for entry in substituter.unresolved.values())


# -- stickiness (D11) --------------------------------------------------------


def fastcs_configs(services_repo: Path) -> dict[str, bytes]:
    """``folder name -> config/fastcs.yaml`` bytes, for every generated IOC."""
    return {
        path.parent.parent.name: path.read_bytes()
        for path in sorted(services_repo.glob("services/*/config/fastcs.yaml"))
    }


def test_rerunning_keeps_the_same_ordinals_and_bytes(
    builder_tree: Path, services_repo: Path, capsys
):
    """D11: ordinals are read back from the repo, never reallocated.

    Renumbering on a re-run would repoint every PV rewritten by the first run at
    a node prefix that no longer exists.
    """
    run_catio(builder_tree, services_repo)
    capsys.readouterr()
    first = fastcs_configs(services_repo)
    assert set(first) == {
        "bl21i-di-catio-01",
        "bl21i-va-catio-01",
        "bl21i-va-catio-05",
        "bl21i-va-catio-06",
    }

    run_catio(builder_tree, services_repo, json_out=True)
    report = json.loads(capsys.readouterr().out)

    assert fastcs_configs(services_repo) == first
    assert folders(services_repo) == {
        name.lower() for name in EXPECTED_IOCS_WRITTEN
    } | set(first)

    ordinals = {c["catio_ioc"]: c["ordinal"] for c in report["chains"]}
    assert ordinals == EXPECTED_ORDINALS


def test_ordinals_match_the_node_prefix_actually_written(
    builder_tree: Path, services_repo: Path, capsys
):
    """The written ``node_prefix`` and the predicted one are one source (D10)."""
    run_catio(builder_tree, services_repo, json_out=True)
    report = json.loads(capsys.readouterr().out)

    for chain in report["chains"]:
        if not chain["converted"]:
            continue
        folder = Path(chain["path"])
        assert folder.parent.parent == services_repo
        written = (folder / "config" / "fastcs.yaml").read_text()
        expected = EXPECTED_ORDINALS[chain["catio_ioc"]]
        assert chain["ordinal"] == expected
        assert f'node_prefix: "{chain["node_prefix"]}"' in written
        assert f"E{expected}RIO" in chain["node_prefix"]
