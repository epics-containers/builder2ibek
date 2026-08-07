"""Tests for the ``builder2ibek catio`` command body.

``builder2ibek.catio.services`` is written by another agent and may not exist
yet, so almost every test here drives the flow through a :class:`StubServices`
injected in place of :func:`builder2ibek.catio.cli._load_services`. The one test
that exercises the real writer skips itself until that module lands. The fake
services-repo fixture is deliberately minimal and local to this file rather than
shared through ``conftest.py``: ``tests/test_catio_services.py`` does not exist
yet, so there is nothing to factor out with, and a premature ``conftest.py``
fixture would collide with whatever that file brings.

Anything that has to predict a fastcs-catio PV name needs `fastcs_catio`, which
builder2ibek's own environment deliberately lacks, so those tests are gated on
``importorskip``. Run them with the side venv:

    env -u EPICS_ROOT .venv-catio/bin/python -m pytest tests/test_catio_cli.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from builder2ibek.__main__ import cli
from builder2ibek.catio import cli as catio_cli_module
from builder2ibek.catio.chains import Chain
from builder2ibek.catio.cli import (
    CatioReport,
    _existing_description,
    _expand_template,
    _is_template_xml,
    _OverriddenChain,
    _placeholder_line,
    _scan_placeholders,
    _xml_dir,
    apply_prefix_overrides,
    catio_cli,
)

CATIO_SAMPLES = Path(__file__).parent / "samples" / "catio"

HAS_FASTCS = importlib.util.find_spec("fastcs_catio") is not None
HAS_SERVICES = importlib.util.find_spec("builder2ibek.catio.services") is not None

needs_fastcs = pytest.mark.skipif(
    not HAS_FASTCS, reason="fastcs_catio is only installed in .venv-catio"
)


# -- doubles -----------------------------------------------------------------


class StubServices:
    """A stand-in for ``builder2ibek.catio.services``.

    Implements the module's contract exactly -- ``read_sticky_ordinals``,
    ``scaffold``, ``write_catio_ioc``, ``write_ioc`` -- and records what it was
    asked to do. Writes just enough real content that the CLI's placeholder
    sweep has something to find.
    """

    def __init__(self, sticky: dict[str, int] | None = None) -> None:
        self.sticky = sticky or {}
        self.written_iocs: list[str] = []
        self.written_chains: list[str] = []
        self.name_mappings: dict[str, dict[str, str]] = {}
        self.dry_runs: set[bool] = set()

    def read_sticky_ordinals(self, services_repo: Path) -> dict[str, int]:
        return dict(self.sticky)

    def scaffold(
        self, services_repo: Path, folder: str, *, fastcs: bool, dry_run: bool
    ) -> Path:
        path = services_repo / "services" / folder
        if not dry_run:
            (path / "config").mkdir(parents=True, exist_ok=True)
        return path

    def write_catio_ioc(
        self, services_repo: Path, chain: Chain, *, dry_run: bool
    ) -> list[str]:
        self.written_chains.append(chain.catio_ioc)
        self.name_mappings[chain.catio_ioc] = chain.name_mappings()
        self.dry_runs.add(dry_run)
        path = self.scaffold(
            services_repo, chain.services_folder, fastcs=True, dry_run=dry_run
        )
        if not dry_run:
            (path / "values.yaml").write_text(
                "ioc-instance:\n  image: REPLACE_WITH_FASTCS_IMAGE_URI\n"
            )
            (path / "config" / "fastcs.yaml").write_text(
                json.dumps(chain.name_mappings())
            )
        return ["REPLACE_WITH_FASTCS_IMAGE_URI"]

    def write_ioc(
        self, services_repo: Path, ioc_name: str, ioc, *, dry_run: bool
    ) -> Path:
        self.written_iocs.append(ioc_name)
        self.dry_runs.add(dry_run)
        path = self.scaffold(
            services_repo, ioc_name.lower(), fastcs=False, dry_run=dry_run
        )
        if not dry_run:
            (path / "values.yaml").write_text(
                "ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n"
            )
            (path / "config" / "ioc.yaml").write_text(
                f"ioc_name: {ioc_name}\ndescription: {ioc.description}\n"
                f"entities: {ioc.entities}\n"
            )
        return path


@pytest.fixture
def stub(monkeypatch) -> StubServices:
    services = StubServices()
    monkeypatch.setattr(catio_cli_module, "_load_services", lambda: services)
    return services


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


#: A synthetic IOC with no EtherCAT anything, standing in for the IOCs this
#: command must leave entirely alone. Synthetic rather than a real sample
#: because several real ones (BL21I-MO-IOC-01 among them) make their converter
#: write a blacklist file into the working directory.
BYSTANDER_XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
    <asyn.AsynIP name="BYSTANDER" port="192.168.0.1:7001"/>
</components>
"""


@pytest.fixture
def builder_tree(tmp_path: Path) -> Path:
    """A BUILDER support module: the four chains, two consumers, one bystander."""
    root = tmp_path / "BL21I-BUILDER"
    make_iocs = root / "etc" / "makeIocs"
    make_iocs.mkdir(parents=True)
    for xml in sorted(CATIO_SAMPLES.glob("*.xml")):
        shutil.copy(xml, make_iocs / xml.name)
    (make_iocs / "BL21I-MO-IOC-99.xml").write_text(BYSTANDER_XML)
    return root


def run_catio(builder_path: Path, services_repo: Path, **kwargs) -> int:
    """Call :func:`catio_cli` and return its exit code rather than raising."""
    try:
        catio_cli(builder_path, services_repo, **kwargs)
    except typer.Exit as exc:
        return int(exc.exit_code)
    return 0


# -- helpers -----------------------------------------------------------------


def test_is_template_xml():
    assert _is_template_xml(Path("GIGE-FIT-TEMPLATE.xml"))
    assert _is_template_xml(Path("$(IOC)-thing.xml"))
    assert not _is_template_xml(Path("BL21I-VA-IOC-02.xml"))


def test_xml_dir_prefers_make_iocs(tmp_path: Path):
    root = tmp_path / "BL21I-BUILDER"
    (root / "etc" / "makeIocs").mkdir(parents=True)
    assert _xml_dir(root) == root / "etc" / "makeIocs"


def test_xml_dir_accepts_a_leaf_folder(tmp_path: Path):
    assert _xml_dir(tmp_path) == tmp_path


def test_expand_template_leaves_fastcs_placeholders_alone():
    chain = Chain("BL21I-VA-IOC-01", "BL21I-VA", 3)
    assert _expand_template("{domain}-E{n}RIO-{:02d}", chain) == (
        "BL21I-VA-E3RIO-{:02d}"
    )
    assert _expand_template("{node_prefix}:{group_alias}{:02d}", chain) == (
        "{node_prefix}:{group_alias}{:02d}"
    )


def test_overridden_chain_feeds_name_mappings():
    base = Chain("BL21I-VA-IOC-01", "BL21I-VA", 2)
    chain = _OverriddenChain(
        base, node_prefix="{domain}-RIO{n}-{:02d}", device_prefix="{id}:EC{:02d}"
    )
    assert chain.node_prefix == "BL21I-VA-RIO2-{:02d}"
    assert chain.name_mappings() == {
        "node_prefix": "BL21I-VA-RIO2-{:02d}",
        "module_prefix": base.module_prefix,
        "device_prefix": "{id}:EC{:02d}",
    }
    # identity of the chain is untouched
    assert chain.catio_ioc == "BL21I-VA-CATIO-01"
    assert chain.services_folder == "bl21i-va-catio-01"


def test_apply_prefix_overrides_is_a_no_op_without_overrides():
    chains = [Chain("BL21I-VA-IOC-01", "BL21I-VA", 1)]
    assert apply_prefix_overrides(chains) is chains


def test_apply_prefix_overrides_wraps_every_chain():
    chains = [
        Chain("BL21I-VA-IOC-01", "BL21I-VA", 1),
        Chain("BL21I-DI-IOC-01", "BL21I-DI", 1),
    ]
    wrapped = apply_prefix_overrides(chains, node_prefix="{domain}-X{n}-{:02d}")
    assert [c.node_prefix for c in wrapped] == [
        "BL21I-VA-X1-{:02d}",
        "BL21I-DI-X1-{:02d}",
    ]


def test_placeholder_line_qualifies_bare_tokens():
    folder = Path("services/bl21i-va-catio-01")
    assert _placeholder_line(folder, "REPLACE_WITH_IMAGE_URI") == (
        "services/bl21i-va-catio-01: REPLACE_WITH_IMAGE_URI"
    )
    assert _placeholder_line(folder, "values.yaml: REPLACE_WITH_X") == (
        "values.yaml: REPLACE_WITH_X"
    )


def test_scan_placeholders_finds_tokens_and_skips_symlinks(tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "chart.yaml").write_text("REPLACE_WITH_SHARED_THING\n")
    folder = tmp_path / "ioc"
    (folder / "config").mkdir(parents=True)
    (folder / "values.yaml").write_text("image: REPLACE_WITH_IMAGE_URI\n")
    (folder / "config" / "ioc.yaml").write_text("description: REPLACE_WITH_DESCRIPTION")
    (folder / "templates").symlink_to(shared)

    found = _scan_placeholders(folder)

    assert any(line.endswith("values.yaml: REPLACE_WITH_IMAGE_URI") for line in found)
    assert any(line.endswith("ioc.yaml: REPLACE_WITH_DESCRIPTION") for line in found)
    assert not any("SHARED" in line for line in found)


def test_scan_placeholders_of_a_missing_folder_is_empty(tmp_path: Path):
    assert _scan_placeholders(tmp_path / "nope") == []


def test_existing_description_round_trips(tmp_path: Path):
    config = tmp_path / "services" / "bl21i-va-ioc-02" / "config"
    config.mkdir(parents=True)
    (config / "ioc.yaml").write_text("description: Vacuum IOC 2\nentities: []\n")
    assert _existing_description(tmp_path, "BL21I-VA-IOC-02") == "Vacuum IOC 2"


def test_existing_description_ignores_scaffold_placeholder(tmp_path: Path):
    config = tmp_path / "services" / "bl21i-va-ioc-02" / "config"
    config.mkdir(parents=True)
    (config / "ioc.yaml").write_text("description: REPLACE_WITH_DESCRIPTION\n")
    assert _existing_description(tmp_path, "BL21I-VA-IOC-02") == ""


def test_existing_description_of_an_unknown_ioc_is_empty(tmp_path: Path):
    assert _existing_description(tmp_path, "BL21I-VA-IOC-02") == ""


def test_existing_description_survives_a_corrupt_file(tmp_path: Path):
    config = tmp_path / "services" / "bl21i-va-ioc-02" / "config"
    config.mkdir(parents=True)
    (config / "ioc.yaml").write_text("description: [unclosed\n")
    assert _existing_description(tmp_path, "BL21I-VA-IOC-02") == ""


# -- CLI surface -------------------------------------------------------------


def test_help_lists_every_option():
    result = CliRunner().invoke(cli, ["catio", "--help"])
    assert result.exit_code == 0
    text = result.output
    for option in (
        "--services-repo",
        "--strict",
        "--no-strict",
        "--dry-run",
        "--json",
        "--node-prefix",
        "--module-prefix",
        "--device-prefix",
    ):
        assert option in text, option
    # typer renders the argument's name differently across versions
    assert "builder_path" in text.lower()


def test_services_repo_is_required(builder_tree: Path, stub: StubServices):
    result = CliRunner().invoke(cli, ["catio", str(builder_tree)])
    assert result.exit_code != 0
    assert stub.written_iocs == []


def test_missing_builder_path_fails_cleanly(
    tmp_path: Path, services_repo: Path, stub: StubServices, capsys
):
    with pytest.raises(typer.Exit) as exc:
        catio_cli(tmp_path / "nope", services_repo)
    assert exc.value.exit_code == 1
    assert "builder path not found" in capsys.readouterr().err


def test_missing_services_repo_fails_cleanly(
    builder_tree: Path, tmp_path: Path, stub: StubServices, capsys
):
    with pytest.raises(typer.Exit) as exc:
        catio_cli(builder_tree, tmp_path / "nope")
    assert exc.value.exit_code == 1
    assert "services repo not found" in capsys.readouterr().err


def test_startup_failure_reports_json_when_asked(
    builder_tree: Path, tmp_path: Path, stub: StubServices, capsys
):
    with pytest.raises(typer.Exit):
        catio_cli(builder_tree, tmp_path / "nope", json_out=True)
    payload = json.loads(capsys.readouterr().out)
    assert "services repo not found" in payload["error"]


@pytest.mark.skipif(
    HAS_FASTCS, reason="only meaningful in an environment without fastcs_catio"
)
def test_without_fastcs_the_error_names_the_side_venv(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    with pytest.raises(typer.Exit) as exc:
        catio_cli(builder_tree, services_repo)
    assert exc.value.exit_code == 1
    err = capsys.readouterr().err
    assert ".venv-catio" in err
    assert stub.written_iocs == []
    assert stub.written_chains == []


# -- end to end --------------------------------------------------------------


# The three BL21I-VA chains convert cleanly; ``BL21I-DI-IOC-01`` does not. Its
# own ``EPICS_BASE.dbpf`` entities set currents on ``BL21I-DI-LED-01`` and
# ``BL21I-OP-LED-01``, PVs created by ``auto_EL2595`` -- a terminal with no leaf
# table in ``leaves.py``, so no fastcs-catio name can be predicted for them.
# That is ``unknown-entity-type``, an ERROR, and it fails the DI chain. Real
# data, not a fixture quirk: fixing it means teaching ``leaves.py`` about
# EL2595/EL4134 or dropping those dbpf lines.
CLEAN_CHAINS = ["BL21I-VA-CATIO-01", "BL21I-VA-CATIO-05", "BL21I-VA-CATIO-06"]
FAILED_CHAIN = "BL21I-DI-IOC-01"


@needs_fastcs
def test_end_to_end_writes_the_clean_chains_and_their_consumers(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    code = run_catio(builder_tree, services_repo)
    out = capsys.readouterr().out

    assert code == 1  # the DI chain errored
    assert sorted(stub.written_chains) == CLEAN_CHAINS
    # every clean scanner, plus the two pure consumers -- and nothing else
    assert sorted(stub.written_iocs) == [
        "BL21I-VA-IOC-01",
        "BL21I-VA-IOC-02",
        "BL21I-VA-IOC-04",
        "BL21I-VA-IOC-05",
        "BL21I-VA-IOC-06",
    ]
    assert "BL21I-MO-IOC-99" not in stub.written_iocs
    assert stub.dry_runs == {False}

    services = services_repo / "services"
    assert (services / "bl21i-va-catio-01" / "config" / "fastcs.yaml").is_file()
    assert (services / "bl21i-va-ioc-02" / "config" / "ioc.yaml").is_file()
    assert not (services / "bl21i-mo-ioc-99").exists()
    assert not (services / "bl21i-di-catio-01").exists()

    assert "Chains discovered: 4" in out
    assert "Chains converted:  3" in out
    assert "Chains failed:     1" in out
    assert "REPLACE_WITH_FASTCS_IMAGE_URI" in out
    assert "REPLACE_WITH_IMAGE_URI" in out
    assert "sticky" in out


@needs_fastcs
def test_the_failed_chain_blocks_its_own_scanner_ioc(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    run_catio(builder_tree, services_repo, json_out=True)
    payload = json.loads(capsys.readouterr().out)

    skipped = {item["ioc"]: item for item in payload["iocs_skipped"]}
    assert list(skipped) == [FAILED_CHAIN]
    assert skipped[FAILED_CHAIN]["blocked_by"] == [FAILED_CHAIN]
    assert skipped[FAILED_CHAIN]["own_errors"] is True
    assert [c for c in payload["chains"] if not c["converted"]] == [
        c for c in payload["chains"] if c["scanner_ioc"] == FAILED_CHAIN
    ]


@needs_fastcs
def test_end_to_end_rewrites_every_legacy_reference(
    builder_tree: Path, services_repo: Path, stub: StubServices
):
    """The whole point: no legacy ERIO PV survives in a written consumer."""
    run_catio(builder_tree, services_repo)
    written = (
        services_repo / "services" / "bl21i-va-ioc-02" / "config" / "ioc.yaml"
    ).read_text()
    assert "-ERIO-" not in written
    assert "BL21I-VA-E1RIO-" in written


@needs_fastcs
def test_dry_run_writes_nothing(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    before = sorted(p.name for p in (services_repo / "services").iterdir())

    run_catio(builder_tree, services_repo, dry_run=True)

    assert stub.dry_runs == {True}
    assert sorted(p.name for p in (services_repo / "services").iterdir()) == before
    out = capsys.readouterr().out
    assert "DRY RUN -- nothing was written" in out
    # the analysis still ran in full
    assert "Chains converted:  3" in out


@needs_fastcs
def test_json_output_is_the_only_thing_on_stdout(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    run_catio(builder_tree, services_repo, json_out=True)
    payload = json.loads(capsys.readouterr().out)

    assert set(payload) >= {
        "chains",
        "iocs_written",
        "iocs_skipped",
        "placeholders",
        "diagnostics",
    }
    assert len(payload["chains"]) == 4
    assert "BL21I-VA-IOC-02" in payload["iocs_written"]
    assert all("severity" in d for d in payload["diagnostics"])
    assert any("REPLACE_WITH" in p for p in payload["placeholders"])


@needs_fastcs
def test_strict_also_fails_the_device_mod_mismatch_chain(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    """--strict promotes device-mod-mismatch, which additionally fails VA-IOC-01."""
    code = run_catio(builder_tree, services_repo, strict=True)
    assert code == 1

    out = capsys.readouterr().out
    assert sorted(stub.written_chains) == ["BL21I-VA-CATIO-05", "BL21I-VA-CATIO-06"]
    assert "Chains failed:     2" in out

    blocked = {
        line.strip().split()[0]
        for line in out.splitlines()
        if "blocked by chain" in line
    }
    assert {"BL21I-DI-IOC-01", "BL21I-VA-IOC-01"} <= blocked


@needs_fastcs
def test_strict_names_the_chain_that_blocked_each_skipped_ioc(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    run_catio(builder_tree, services_repo, strict=True, json_out=True)
    payload = json.loads(capsys.readouterr().out)

    skipped = {item["ioc"]: item for item in payload["iocs_skipped"]}
    assert skipped["BL21I-VA-IOC-01"]["blocked_by"] == ["BL21I-VA-IOC-01"]
    # A consumer of a skipped chain is reported even though the chain was
    # dropped before substitution, so its references never resolved at all.
    assert skipped["BL21I-VA-IOC-02"]["own_errors"] is True
    assert all("blocked_by" in item for item in payload["iocs_skipped"])


@needs_fastcs
def test_node_prefix_override_reaches_the_generated_ioc(
    builder_tree: Path, services_repo: Path, stub: StubServices, capsys
):
    run_catio(
        builder_tree, services_repo, node_prefix="{domain}-CAT{n}-{:02d}", json_out=True
    )
    payload = json.loads(capsys.readouterr().out)

    predicted = {c["catio_ioc"]: c["node_prefix"] for c in payload["chains"]}
    assert predicted["BL21I-VA-CATIO-01"] == "BL21I-VA-CAT1-{:02d}"
    # the names written into config/fastcs.yaml come from the same source
    assert stub.name_mappings["BL21I-VA-CATIO-01"]["node_prefix"] == (
        "BL21I-VA-CAT1-{:02d}"
    )
    written = (
        services_repo / "services" / "bl21i-va-ioc-02" / "config" / "ioc.yaml"
    ).read_text()
    assert "BL21I-VA-CAT1-" in written


@needs_fastcs
def test_sticky_ordinals_are_honoured(
    builder_tree: Path, services_repo: Path, monkeypatch, capsys
):
    stub = StubServices(sticky={"BL21I-VA-CATIO-01": 7})
    monkeypatch.setattr(catio_cli_module, "_load_services", lambda: stub)

    run_catio(builder_tree, services_repo, json_out=True)
    payload = json.loads(capsys.readouterr().out)

    ordinals = {c["catio_ioc"]: c["ordinal"] for c in payload["chains"]}
    assert ordinals["BL21I-VA-CATIO-01"] == 7
    assert ordinals["BL21I-VA-CATIO-05"] == 1


@needs_fastcs
def test_the_command_is_reachable_through_the_typer_app(
    builder_tree: Path, services_repo: Path, stub: StubServices
):
    result = CliRunner().invoke(
        cli,
        ["catio", str(builder_tree), "--services-repo", str(services_repo), "--json"],
    )
    assert result.exit_code == 1, result.output
    assert sorted(stub.written_chains) == CLEAN_CHAINS


@pytest.mark.skipif(
    not HAS_SERVICES, reason="builder2ibek.catio.services not written yet"
)
@needs_fastcs
def test_end_to_end_with_the_real_services_writer(
    builder_tree: Path, services_repo: Path
):
    """Loose on purpose: the contract's outcome, not services.py's internals."""
    run_catio(builder_tree, services_repo)
    services = services_repo / "services"
    assert (services / "bl21i-va-catio-01").is_dir()
    assert (services / "bl21i-va-ioc-02" / "config" / "ioc.yaml").is_file()
    assert not (services / "bl21i-mo-ioc-99").exists()
    assert not (services / "bl21i-di-catio-01").exists()


def test_report_renders_without_any_placeholders():
    from builder2ibek.catio.diagnostics import DiagnosticLog

    report = CatioReport(
        builder_path="/b", services_repo="/s", strict=False, dry_run=False
    )
    text = catio_cli_module._render_report(report, DiagnosticLog())
    assert "Placeholders to fill in:\n  (none)" in text
    assert "0 errors, 0 warnings" in text
