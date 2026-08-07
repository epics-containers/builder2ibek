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

#: ``BL21I-DI-IOC-01`` is skipped: it ``dbpf``-writes PVs created by
#: ``auto_EL2595``, a terminal type ``leaves.py`` has no translation table for,
#: so ``unknown-entity-type`` (ERROR) fails its chain. See the module docstring
#: of ``builder2ibek.catio.leaves`` for what adding one would take.
EXPECTED_FAILED_CHAINS = {"BL21I-DI-IOC-01"}

#: Consumers of a clean chain, so they are rewritten and written out.
EXPECTED_IOCS_WRITTEN = {
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

    # Non-zero because BL21I-DI-IOC-01's chain failed.
    assert code != 0

    expected = {name.lower() for name in EXPECTED_IOCS_WRITTEN} | {
        "bl21i-va-catio-01",
        "bl21i-va-catio-05",
        "bl21i-va-catio-06",
    }
    assert folders(services_repo) == expected

    # The failed chain got neither a fastcs-catio IOC nor a rewritten scanner.
    assert not (services_repo / "services" / "bl21i-di-catio-01").exists()
    assert not (services_repo / "services" / "bl21i-di-ioc-01").exists()


def test_report_names_the_diagnostic_that_blocked_the_failed_chain(
    builder_tree: Path, services_repo: Path, capsys
):
    """A skipped chain must be traceable to a named, actionable diagnostic."""
    run_catio(builder_tree, services_repo, json_out=True)
    report = json.loads(capsys.readouterr().out)

    failed = {c["scanner_ioc"] for c in report["chains"] if not c["converted"]}
    assert failed == EXPECTED_FAILED_CHAINS

    blocking = [
        d
        for d in report["diagnostics"]
        if d["severity"] == "error" and d["chain"] in EXPECTED_FAILED_CHAINS
    ]
    assert blocking, "a failed chain must carry at least one error"
    assert {d["code"] for d in blocking} == {"unknown-entity-type"}
    # The message must name the terminal type a human has to add a table for.
    assert all("EL2595" in d["message"] for d in blocking)

    assert [i["ioc"] for i in report["iocs_skipped"]] == ["BL21I-DI-IOC-01"]
    assert report["iocs_skipped"][0]["blocked_by"] == ["BL21I-DI-IOC-01"]


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
EXPECTED_SUBSTITUTIONS = 526


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
