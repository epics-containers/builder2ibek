"""Tests for builder2ibek.devc7 against a mock /dls_sw tree and services repo.

All names are fictional: beamline BL99J lives in the bl99i services repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from builder2ibek import devc7
from builder2ibek.__main__ import cli

PROD = "/dls_sw/prod/R3.14.12.7/ioc/BL99J"
PROD7 = "/dls_sw/prod/R7.0.7/ioc/BL99J"
PROD_I = "/dls_sw/prod/R3.14.12.7/ioc/BL99I"
WORK = "/dls_sw/work/R3.14.12.7/support/BL99J-BUILDER/iocs"
LX = "bin/linux-x86_64"

TEMPLATE_VALUES = """\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

dev-c7:
  # prod #######################################################################
  # To run a dls_sw/prod IOC only set iocVersion.
  #
  iocVersion: REPLACE WITH IOC PROD VERSION (eg 2-1)
  #
  # work #######################################################################
  # iocPath: /dls_sw/work/R3.14.12.7/support/BL45P-BUILDER/iocs
"""

REDIRECT = f"""\
# comment line
BL99J-MO-IOC-01 {PROD}/BL99J-MO-IOC-01/2-3/bin/linux-x86_64/stBL99J-MO-IOC-01.sh
BL99J-MO-IOC-01 {PROD}/BL99J-MO-IOC-01/0-1/bin/linux-x86_64/stBL99J-MO-IOC-01.sh
BL99J-EA-IOC-02 {PROD}/BL99J-EA-IOC-02/1-0/bin/windows-x64/stBL99J-EA-IOC-02.bat
BL99J-VA-IOC-03 {PROD}/BL99J-VA-IOC-03/1-0/bin/vxWorks-ppc604_long/st.boot
BL99J-DI-IOC-04 {PROD}/BL99J-DI-IOC-04/1-0/bin/RTEMS-beatnik/stBL99J-DI-IOC-04.boot
BL99J-EA-IOC-05 {PROD7}/BL99J-EA-IOC-05/3-1/{LX}/stBL99J-EA-IOC-05.sh
BL99J-MO-IOC-06 {WORK}/BL99J-MO-IOC-06/{LX}/stBL99J-MO-IOC-06.sh
BL99J-BL-IOC-07 {PROD}/BL/1-0/bin/linux-x86_64/stBL99J-BL-IOC-07.boot
BL99J-ML-MALC-01 /dls_sw/work/R3.14.12.7/ioc/BL99J/BL99J-ML-MALC-01/malc.yaml

BL99J-MO-IOC-08\t{PROD}/BL99J-MO-IOC-08/1-0/bin/linux-x86_64/stBL99J-MO-IOC-08.sh
BL99J-CS-IOC-09 {PROD}/BL99J-CS-IOC-09/1-0/bin/linux-x86_64/stBL99J-CS-IOC-09.sh
BL99J-EA-IOC-99 {PROD}/BL99J-EA-IOC-99/1-0/bin/linux-x86_64/stBL99J-EA-IOC-99.sh
BL99I-MO-IOC-01 {PROD_I}/BL99I-MO-IOC-01/4-0/{LX}/stBL99I-MO-IOC-01.sh
BL99J-EA-IOC-14 {PROD}/BL99J-EA-IOC-14/1-0/{LX}/stBL99J-EA-IOC-14.sh
"""

SOFT_IOCS = {
    "bl99j-mo-serv-01": """\
autoProcServControl 7099
BL99J-MO-IOC-01 7001
BL99J-MO-IOC-06 7002 manualstart

\t
BL99J-MO-IOC-08\t7003\t# comment
BL99J-MO-IOC-10 7004
BL99J-MO-IOC-11 7005
""",
    "bl99j-ea-serv-01": """\
BL99J-EA-IOC-02 7001
BL99J-EA-IOC-05 7002 5066
BL99J-BL-IOC-07 7003
BL99J-ML-MALC-01 7004
BL99J-CS-IOC-09 7005
BL99J-NO-IOC-12 7006
BL99J-EA-IOC-99 7008
BL99I-MO-IOC-01 7007
BL99J-EA-IOC-14 7009
""",
}
REAL_IOCS = {
    "bl99j-va-serv-01": "BL99J-VA-IOC-03 bl99j-va-ioc-03 7001\n"
    "BL99J-DI-IOC-04 bl99j-di-ioc-04 7002\n",
}

# Builds present on the mock /dls_sw
BUILDS = [
    f"{PROD}/BL99J-MO-IOC-01/2-3/bin/linux-x86_64/stBL99J-MO-IOC-01.sh",
    f"{PROD7}/BL99J-EA-IOC-05/3-1/{LX}/stBL99J-EA-IOC-05.sh",
    f"{WORK}/BL99J-MO-IOC-06/{LX}/stBL99J-MO-IOC-06.sh",
    f"{PROD}/BL99J-MO-IOC-06/1-4/bin/linux-x86_64/stBL99J-MO-IOC-06.sh",
    f"{PROD}/BL/1-0/bin/linux-x86_64/stBL99J-BL-IOC-07.boot",
    f"{PROD}/BL99J-MO-IOC-08/1-0/bin/linux-x86_64/stBL99J-MO-IOC-08.sh",
    f"{PROD}/BL99J-CS-IOC-09/1-0/bin/linux-x86_64/stBL99J-CS-IOC-09.sh",
    f"{PROD}/BL99J-CS-IOC-09/1-0/bin/linux-x86_64/stBL99J-CS-IOC-09-sim.sh",
    # not in the redirect table: reported, 1-10 > 1-9
    f"{PROD}/BL99J-MO-IOC-10/1-9/bin/linux-x86_64/stBL99J-MO-IOC-10.sh",
    f"{PROD}/BL99J-MO-IOC-10/1-10/bin/linux-x86_64/stBL99J-MO-IOC-10.sh",
    f"{PROD}/BL99J-MO-IOC-11/1-0/bin/windows-x64/stBL99J-MO-IOC-11.bat",
    f"{PROD_I}/BL99I-MO-IOC-01/4-0/{LX}/stBL99I-MO-IOC-01.sh",
]


@pytest.fixture
def dls_sw(tmp_path: Path) -> Path:
    root = tmp_path / "dls_sw"
    redirector = root / "prod/etc/redirector"
    redirector.mkdir(parents=True)
    (redirector / "redirect_table").write_text(REDIRECT)
    for kind, files in (("soft-iocs", SOFT_IOCS), ("real-iocs", REAL_IOCS)):
        for server, text in files.items():
            (root / "prod/etc/init" / server).mkdir(parents=True, exist_ok=True)
            (root / "prod/etc/init" / server / kind).write_text(text)
    for build in BUILDS:
        path = root / Path(build).relative_to("/dls_sw")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
    return root


@pytest.fixture
def services_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "bl99i-services"
    shared = repo / ".helm-shared"
    shared.mkdir(parents=True)
    (shared / "LegacyChart.yaml").write_text("name: ec-legacy-service\n")
    template = repo / "services" / devc7.TEMPLATE
    template.mkdir(parents=True)
    (template / "values.yaml").write_text(TEMPLATE_VALUES)
    os.symlink("../../.helm-shared/LegacyChart.yaml", template / "Chart.yaml")
    (repo / "services/values.yaml").write_text(
        "global:\n  domain: i99\n  location: bl99i\nshared: &shared\n"
        "  hostNetwork: true\ndev-c7:\n  <<: *shared\n"
    )
    existing = repo / "services/bl99j-ea-ioc-99/config"
    existing.mkdir(parents=True)
    (existing / "ioc.yaml").write_text("ioc_name: bl99j-ea-ioc-99\n")
    return repo


def _plan(
    services_repo: Path, dls_sw: Path, prefix: str = "BL99J", enable: bool = False
) -> devc7.Plan:
    return devc7.build_plan(prefix, services_repo, dls_sw=dls_sw, enable=enable)


def _by_ioc(plan: devc7.Plan) -> dict[str, devc7.PlanEntry]:
    return {e.ioc: e for e in plan.entries}


def test_standard_prod_ioc_gets_version_and_domain(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-MO-IOC-01"]
    assert entry.action == "add"
    assert entry.source == "redirector"
    # the redirector takes the first matching line
    assert entry.version == "2-3"
    assert entry.source_ref.endswith("redirect_table:2")
    assert entry.values == {"iocVersion": "2-3", "epicsDomain": "BL99J"}
    assert entry.folder == "bl99j-mo-ioc-01"
    assert any(
        n.startswith("duplicate redirect entries (lines 2, 3)") for n in entry.notes
    )


def test_tabs_and_blank_lines(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-MO-IOC-08"]
    assert entry.action == "add"
    assert entry.values == {"iocVersion": "1-0", "epicsDomain": "BL99J"}
    assert entry.notes == []


def test_launch_arguments_noted(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-EA-IOC-05"]
    assert "launch arguments on bl99j-ea-serv-01: 5066" in entry.notes


def test_new_folders_disabled_unless_enabled(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-MO-IOC-01"]
    assert not entry.enabled
    assert "stopped on bl99j-mo-serv-01" in entry.enabled_comment
    entry = _by_ioc(_plan(services_repo, dls_sw, enable=True))["BL99J-MO-IOC-01"]
    assert entry.enabled
    assert entry.enabled_comment == ""


def test_manualstart_always_disabled(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw, enable=True))["BL99J-MO-IOC-06"]
    assert not entry.enabled
    assert entry.enabled_comment.startswith("manualstart on bl99j-mo-serv-01")


def test_same_domain_as_location_needs_no_domain(services_repo, dls_sw):
    plan = _plan(services_repo, dls_sw, prefix="BL99I")
    assert [e.ioc for e in plan.entries] == ["BL99I-MO-IOC-01"]
    assert plan.entries[0].values == {"iocVersion": "4-0"}


def test_epics_version_set_when_not_default(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-EA-IOC-05"]
    assert entry.values == {
        "iocVersion": "3-1",
        "epicsDomain": "BL99J",
        "epicsVersion": "R7.0.7",
    }


@pytest.mark.parametrize(
    "ioc, reason",
    [
        ("BL99J-EA-IOC-02", "Windows IOC (windows-x64)"),
        ("BL99J-VA-IOC-03", "vxWorks IOC (vxWorks-ppc604_long)"),
        ("BL99J-DI-IOC-04", "RTEMS IOC (RTEMS-beatnik)"),
        ("BL99J-ML-MALC-01", "Malcolm YAML definition, not an IOC startup script"),
        ("BL99J-EA-IOC-99", "services folder exists (ibek)"),
        ("BL99J-NO-IOC-12", "in launch list but no redirect entry, so it cannot boot"),
        ("BL99J-MO-IOC-10", "in launch list but no redirect entry, so it cannot boot"),
        ("BL99J-MO-IOC-11", "in launch list but no redirect entry, so it cannot boot"),
        (
            "BL99J-EA-IOC-14",
            f"boot script missing: {PROD}/BL99J-EA-IOC-14/1-0/{LX}/"
            "stBL99J-EA-IOC-14.sh",
        ),
    ],
)
def test_skips(services_repo, dls_sw, ioc, reason):
    entry = _by_ioc(_plan(services_repo, dls_sw))[ioc]
    assert entry.action == "skip"
    assert entry.reason == reason


def test_no_redirect_reports_newest_build(services_repo, dls_sw):
    entries = _by_ioc(_plan(services_repo, dls_sw))
    assert entries["BL99J-MO-IOC-10"].source == "none"
    assert entries["BL99J-MO-IOC-10"].notes == [
        f"newest build: {PROD}/BL99J-MO-IOC-10/1-10/{LX}/stBL99J-MO-IOC-10.sh"
    ]
    assert entries["BL99J-NO-IOC-12"].notes == ["newest build: none in /dls_sw/prod"]


def test_version_key():
    versions = ["2020-R7-Run2-2", "2020-Run5-1", "1-9", "1-10", "0-4-1"]
    assert sorted(versions, key=devc7._version_key) == [
        "0-4-1",
        "1-9",
        "1-10",
        "2020-R7-Run2-2",
        "2020-Run5-1",
    ]


def test_work_area_ioc_uses_ioc_path(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-MO-IOC-06"]
    assert entry.values == {
        "iocPath": "/dls_sw/work/R3.14.12.7/support/BL99J-BUILDER/iocs"
    }
    assert entry.version == "work"
    assert "runs from /dls_sw/work: needs a release" in entry.notes
    assert "newest prod build is 1-4" in entry.notes


def test_shared_ioc_folder_gets_explicit_entrypoint(services_repo, dls_sw):
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-BL-IOC-07"]
    assert entry.version == "1-0"
    assert entry.values == {
        "workingDir": f"{PROD}/BL/1-0",
        "args": ["stdio-expose ./bin/linux-x86_64/stBL99J-BL-IOC-07.boot"],
    }


def test_several_start_scripts_get_explicit_entrypoint(services_repo, dls_sw):
    # the chart's default st*.sh glob would match two scripts
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-CS-IOC-09"]
    assert entry.values["args"] == [
        "stdio-expose ./bin/linux-x86_64/stBL99J-CS-IOC-09.sh"
    ]


def test_retired_iocs_listed_not_planned(services_repo, dls_sw):
    assert _plan(services_repo, dls_sw).retired == []
    (dls_sw / "prod/etc/redirector/redirect_table").write_text(
        REDIRECT + f"BL99J-EA-IOC-13 {PROD}/BL99J-EA-IOC-13/1-0/bin/x/st.sh\n"
    )
    plan = _plan(services_repo, dls_sw)
    assert [r["ioc"] for r in plan.retired] == ["BL99J-EA-IOC-13"]
    assert "BL99J-EA-IOC-13" not in _by_ioc(plan)


def test_dry_run_writes_nothing(services_repo, dls_sw):
    before = sorted(p.name for p in (services_repo / "services").iterdir())
    _plan(services_repo, dls_sw)
    assert sorted(p.name for p in (services_repo / "services").iterdir()) == before


def test_apply_writes_folders(services_repo, dls_sw):
    plan = _plan(services_repo, dls_sw)
    written = devc7.apply_plan(plan)
    assert len(written) == sum(e.action == "add" for e in plan.entries)

    folder = services_repo / "services/bl99j-mo-ioc-01"
    chart = folder / "Chart.yaml"
    assert chart.is_symlink()
    assert os.readlink(chart) == "../../.helm-shared/LegacyChart.yaml"
    text = (folder / "values.yaml").read_text()
    assert "REPLACE" not in text
    assert "# work ####" in text  # comments kept
    assert "securityContext" not in text
    assert "# Not deployed until the IOC is stopped on bl99j-mo-serv-01" in text
    values = YAML(typ="safe").load(text)
    assert values == {
        "global": {"enabled": False},
        "dev-c7": {"iocVersion": "2-3", "epicsDomain": "BL99J"},
    }

    bl = YAML(typ="safe").load(
        (services_repo / "services/bl99j-bl-ioc-07/values.yaml").read_text()
    )
    assert bl["dev-c7"]["args"] == [
        "stdio-expose ./bin/linux-x86_64/stBL99J-BL-IOC-07.boot"
    ]


def test_apply_enabled(services_repo, dls_sw):
    devc7.apply_plan(_plan(services_repo, dls_sw, enable=True))
    text = (services_repo / "services/bl99j-mo-ioc-01/values.yaml").read_text()
    assert "global:" not in text
    manual = YAML(typ="safe").load(
        (services_repo / "services/bl99j-mo-ioc-06/values.yaml").read_text()
    )
    assert manual["global"] == {"enabled": False}


@pytest.mark.parametrize("kind", ["folder", "dangling-link"])
def test_apply_writes_nothing_if_any_target_exists(services_repo, dls_sw, kind):
    services = services_repo / "services"
    before = sorted(p.name for p in services.iterdir())
    plan = _plan(services_repo, dls_sw)
    # a target that appears between planning and writing
    racing = services / "bl99j-mo-ioc-08"
    if kind == "folder":
        racing.mkdir()
    else:
        racing.symlink_to("nowhere")
    with pytest.raises(FileExistsError, match="bl99j-mo-ioc-08"):
        devc7.apply_plan(plan)
    assert sorted(p.name for p in services.iterdir()) == sorted(
        [*before, "bl99j-mo-ioc-08"]
    )


def test_dangling_link_counts_as_existing(services_repo, dls_sw):
    (services_repo / "services/bl99j-mo-ioc-08").symlink_to("nowhere")
    entry = _by_ioc(_plan(services_repo, dls_sw))["BL99J-MO-IOC-08"]
    assert entry.reason == "services folder exists (other)"


def test_apply_twice_adds_nothing(services_repo, dls_sw):
    devc7.apply_plan(_plan(services_repo, dls_sw))

    # a second run plans nothing and reports what exists
    again = _plan(services_repo, dls_sw)
    assert not [e for e in again.entries if e.action == "add"]
    assert (
        _by_ioc(again)["BL99J-MO-IOC-08"].reason
        == "services folder exists (dev-c7 legacy)"
    )


def test_render_values_disabled():
    text = devc7.render_values("# head\n\ndev-c7:\n", {"iocVersion": "1-0"}, "why")
    assert text == (
        "# head\n\n# why\nglobal:\n  enabled: false\n\ndev-c7:\n  iocVersion: 1-0\n"
    )


def test_render_values_tab_indent():
    text = devc7.render_values("dev-c7:\n\tiocVersion: REPLACE\n", {"a": "b"})
    assert text == "dev-c7:\n\ta: b\n"


def test_render_values_without_placeholder():
    text = devc7.render_values("dev-c7:\n  # c\n", {"iocVersion": "1-0"})
    assert text == "dev-c7:\n  iocVersion: 1-0\n  # c\n"


def test_render_values_quotes_non_strings():
    text = devc7.render_values(TEMPLATE_VALUES, {"iocVersion": "2.0"})
    assert YAML(typ="safe").load(text)["dev-c7"]["iocVersion"] == "2.0"


def test_emitted_keys_are_chart_keys(services_repo, dls_sw):
    # keys of the dev-c7 chart 2025.11.1 values schema used here
    chart_keys = {
        "iocVersion",
        "epicsDomain",
        "epicsVersion",
        "iocName",
        "iocPath",
        "workingDir",
        "args",
    }
    for entry in _plan(services_repo, dls_sw).entries:
        assert set(entry.values) <= chart_keys


def _cli_args(services_repo: Path, dls_sw: Path) -> list[str]:
    return [
        "dev-c7",
        "BL99J",
        "--services-repo",
        str(services_repo),
        "--dls-sw",
        str(dls_sw),
    ]


def test_cli_dry_run_and_json(services_repo, dls_sw):
    runner = CliRunner()
    result = runner.invoke(cli, _cli_args(services_repo, dls_sw))
    assert result.exit_code == 0, result.output
    assert "BL99J-MO-IOC-01" in result.output
    assert "dry run" in result.output
    assert not (services_repo / "services/bl99j-mo-ioc-01").exists()

    result = runner.invoke(cli, [*_cli_args(services_repo, dls_sw), "--json"])
    data = json.loads(result.output)
    assert data["prefix"] == "BL99J"
    assert data["location"] == "bl99i"
    # --dls-sw moves the init and redirector defaults with it
    assert data["sources"][0] == str(dls_sw / "prod/etc/redirector/redirect_table")


def test_cli_apply(services_repo, dls_sw):
    result = CliRunner().invoke(cli, [*_cli_args(services_repo, dls_sw), "--apply"])
    assert result.exit_code == 0, result.output
    assert (services_repo / "services/bl99j-mo-ioc-01/values.yaml").is_file()


def test_cli_explicit_sources(services_repo, dls_sw, tmp_path):
    init = tmp_path / "init"
    (init / "bl99j-x-serv-01").mkdir(parents=True)
    (init / "bl99j-x-serv-01/soft-iocs").write_text("BL99J-MO-IOC-01 7001\n")
    args = [
        *_cli_args(services_repo, dls_sw),
        "--init-dir",
        str(init),
        "--json",
    ]
    data = json.loads(CliRunner().invoke(cli, args).output)
    assert [e["ioc"] for e in data["entries"]] == ["BL99J-MO-IOC-01"]


def test_cli_write_error(services_repo, dls_sw, monkeypatch):
    def fail(_plan):
        raise PermissionError("read-only")

    monkeypatch.setattr(devc7, "apply_plan", fail)
    result = CliRunner().invoke(cli, [*_cli_args(services_repo, dls_sw), "--apply"])
    assert result.exit_code == 1
    assert "read-only" in result.output


def test_cli_missing_services(tmp_path, dls_sw):
    result = CliRunner().invoke(cli, _cli_args(tmp_path / "nope", dls_sw))
    assert result.exit_code == 1


def test_cli_missing_template(services_repo, dls_sw):
    template = services_repo / "services" / devc7.TEMPLATE
    (template / "values.yaml").unlink()
    result = CliRunner().invoke(cli, [*_cli_args(services_repo, dls_sw), "--apply"])
    assert result.exit_code == 1
