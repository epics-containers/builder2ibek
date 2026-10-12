"""Tests for :mod:`builder2ibek.catio.services`.

Every test builds a throwaway services repo in ``tmp_path`` with the same shape
as ``/workspaces/i21-services``: relative ``Chart.yaml`` / ``templates``
symlinks into ``../../.helm-shared/``, an ``.ioc_template`` and a
``.fastcs_ioc_template``. Nothing here touches a real repo.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from builder2ibek.catio.chains import Chain
from builder2ibek.catio.services import (
    CATIO_CONTROLLER_TYPE,
    IBEK_PLACEHOLDERS,
    IOC_SCHEMA,
    is_legacy,
    read_sticky_ordinals,
    scaffold,
    write_catio_ioc,
    write_ioc,
)
from builder2ibek.types import Generic_IOC

CHART = "\n".join(
    [
        "# A Helm Chart for an IOC instance",
        "apiVersion: v2",
        "name: ec-service",
        "version: 1.0.1",
        "",
    ]
)

LEGACY_CHART = "\n".join(
    [
        "# A Helm Chart for an IOC instance",
        "apiVersion: v2",
        "name: ec-legacy-service",
        "version: 1.0.0",
        "",
    ]
)

IOC_TEMPLATE_VALUES = """\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: REPLACE_WITH_IMAGE_URI
"""

IOC_TEMPLATE_CONFIG = """\
# yaml-language-server: $schema=../ioc.schema.json

ioc_name: "{{ _global.get_env('IOC_NAME') }}"

description: REPLACE_WITH_DESCRIPTION

entities: []
"""

FASTCS_TEMPLATE_VALUES = """\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: REPLACE_WITH_FASTCS_IMAGE_URI
  args:
    - stdio-socket --ptty "fastcs-example run /epics/ioc/config/controller.yaml"

  livenessExecutable: ""
  preStopExecutable: ""
"""

FASTCS_TEMPLATE_CONFIG = """\
# EXAMPLE CONTROLLER CONFIGURATION YAML REPLACE WITH YOURS

controller:
  ip_settings:
    ip: "localhost"
"""

LEGACY_VALUES = """\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

dev-c7:
  iocVersion: 5-19
"""

#: A real ibek IOC whose *image tag* contains "dev-c7". Deleting this folder
#: would be a data-loss bug -- ``bl21i-ea-ioc-01-debug`` is exactly this shape.
DEV_C7_IMAGE_VALUES = """\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: ghcr.io/diamondlightsource/dev-c7:2025.11.1-beta.1
"""


def _link(where: Path, name: str, target: str) -> None:
    os.symlink(target, where / name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal but structurally faithful services repo."""
    shared = tmp_path / ".helm-shared"
    (shared / "templates").mkdir(parents=True)
    (shared / "Chart.yaml").write_text(CHART)
    (shared / "LegacyChart.yaml").write_text(LEGACY_CHART)
    (shared / "values.schema.json").write_text("{}\n")
    (shared / "templates" / "ioc_instance.yaml").write_text(
        '{{ include "ioc-instance" . }}\n'
    )

    services = tmp_path / "services"

    ibek = services / ".ioc_template"
    (ibek / "config").mkdir(parents=True)
    _link(ibek, "Chart.yaml", "../../.helm-shared/Chart.yaml")
    _link(ibek, "templates", "../../.helm-shared/templates")
    (ibek / "values.yaml").write_text(IOC_TEMPLATE_VALUES)
    (ibek / "config" / "ioc.yaml").write_text(IOC_TEMPLATE_CONFIG)

    fastcs = services / ".fastcs_ioc_template"
    (fastcs / "config").mkdir(parents=True)
    _link(fastcs, "Chart.yaml", "../../.helm-shared/Chart.yaml")
    _link(fastcs, "templates", "../../.helm-shared/templates")
    (fastcs / "values.yaml").write_text(FASTCS_TEMPLATE_VALUES)
    (fastcs / "config" / "controller.yaml").write_text(FASTCS_TEMPLATE_CONFIG)

    return tmp_path


@pytest.fixture
def chain() -> Chain:
    return Chain(scanner_ioc="BL21I-VA-IOC-01", domain="BL21I-VA", ordinal=1)


def _make_legacy(repo: Path, folder: str) -> Path:
    """A ``dev-c7`` IOC folder, exactly as the real ones look."""
    target = repo / "services" / folder
    target.mkdir(parents=True)
    _link(target, "Chart.yaml", "../../.helm-shared/LegacyChart.yaml")
    (target / "values.yaml").write_text(LEGACY_VALUES)
    return target


def _load(path: Path):
    return YAML(typ="safe").load(path)


# --- scaffold ----------------------------------------------------------------


@pytest.mark.parametrize("fastcs", [False, True])
def test_scaffold_creates_relative_symlinks(repo: Path, fastcs: bool) -> None:
    folder = scaffold(repo, "bl21i-va-catio-01", fastcs=fastcs, dry_run=False)

    chart = folder / "Chart.yaml"
    templates = folder / "templates"
    assert chart.is_symlink()
    assert templates.is_symlink()
    assert os.readlink(chart) == "../../.helm-shared/Chart.yaml"
    assert os.readlink(templates) == "../../.helm-shared/templates"
    # and the relative links actually resolve inside this repo
    assert chart.resolve() == (repo / ".helm-shared" / "Chart.yaml").resolve()
    assert (templates / "ioc_instance.yaml").is_file()


def test_scaffold_copies_template_files(repo: Path) -> None:
    folder = scaffold(repo, "bl21i-va-ioc-09", fastcs=False, dry_run=False)
    assert (folder / "values.yaml").read_text() == IOC_TEMPLATE_VALUES
    assert (folder / "config" / "ioc.yaml").read_text() == IOC_TEMPLATE_CONFIG


def test_scaffold_fastcs_uses_the_fastcs_template(repo: Path) -> None:
    folder = scaffold(repo, "bl21i-va-catio-01", fastcs=True, dry_run=False)
    assert (folder / "config" / "controller.yaml").is_file()
    assert not (folder / "config" / "ioc.yaml").exists()


def test_scaffold_dry_run_writes_nothing(repo: Path) -> None:
    before = sorted(p.name for p in (repo / "services").iterdir())
    folder = scaffold(repo, "bl21i-va-catio-01", fastcs=True, dry_run=True)

    assert folder == repo / "services" / "bl21i-va-catio-01"
    assert not folder.exists()
    assert sorted(p.name for p in (repo / "services").iterdir()) == before


def test_scaffold_needs_a_services_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no services directory"):
        scaffold(tmp_path, "bl21i-va-catio-01", fastcs=False, dry_run=False)


@pytest.mark.parametrize(
    "folder", ["", ".legacy_ioc_template", ".ioc_template", "..", "a/b"]
)
def test_scaffold_refuses_a_non_instance_folder(repo: Path, folder: str) -> None:
    """`.legacy_ioc_template` is itself a dev-c7 folder -- never delete it."""
    with pytest.raises(ValueError, match="not an IOC instance folder name"):
        scaffold(repo, folder, fastcs=False, dry_run=False)
    assert (repo / "services" / ".ioc_template" / "values.yaml").is_file()


def test_scaffold_needs_the_template(repo: Path) -> None:
    shutil.rmtree(repo / "services" / ".fastcs_ioc_template")
    with pytest.raises(FileNotFoundError, match=r"\.fastcs_ioc_template"):
        scaffold(repo, "bl21i-va-catio-01", fastcs=True, dry_run=False)


def test_scaffold_keeps_an_existing_non_legacy_folder(repo: Path) -> None:
    folder = repo / "services" / "bl21i-va-ioc-09"
    (folder / "config").mkdir(parents=True)
    (folder / "values.yaml").write_text("ioc-instance:\n  image: real:1.2.3\n")
    (folder / "config" / "ioc.yaml").write_text("description: mine\n")
    (folder / "keep-me.yaml").write_text("hand written\n")

    scaffold(repo, "bl21i-va-ioc-09", fastcs=False, dry_run=False)

    # nothing real was clobbered ...
    assert (folder / "values.yaml").read_text() == (
        "ioc-instance:\n  image: real:1.2.3\n"
    )
    assert (folder / "config" / "ioc.yaml").read_text() == "description: mine\n"
    assert (folder / "keep-me.yaml").is_file()
    # ... but the missing symlinks were added
    assert (folder / "Chart.yaml").is_symlink()
    assert (folder / "templates").is_symlink()


def test_scaffold_recreates_a_folder_linked_to_the_legacy_chart(repo: Path) -> None:
    """A LegacyChart link alone makes a folder legacy, dev-c7 key or not."""
    folder = repo / "services" / "bl21i-va-ioc-09"
    folder.mkdir(parents=True)
    _link(folder, "Chart.yaml", "../../.helm-shared/LegacyChart.yaml")
    (folder / "values.yaml").write_text("ioc-instance: {}\n")

    scaffold(repo, "bl21i-va-ioc-09", fastcs=False, dry_run=False)

    assert os.readlink(folder / "Chart.yaml") == "../../.helm-shared/Chart.yaml"
    assert (folder / "values.yaml").read_text() == IOC_TEMPLATE_VALUES


def test_scaffold_repoints_a_stale_symlink(repo: Path) -> None:
    """A non-legacy folder whose links drifted is repaired, not deleted."""
    folder = repo / "services" / "bl21i-va-ioc-09"
    folder.mkdir(parents=True)
    _link(folder, "Chart.yaml", "../../../elsewhere/Chart.yaml")
    _link(folder, "templates", "../../../elsewhere/templates")
    (folder / "values.yaml").write_text("ioc-instance:\n  image: real:1.2.3\n")

    scaffold(repo, "bl21i-va-ioc-09", fastcs=False, dry_run=False)

    assert os.readlink(folder / "Chart.yaml") == "../../.helm-shared/Chart.yaml"
    assert os.readlink(folder / "templates") == "../../.helm-shared/templates"
    assert "real:1.2.3" in (folder / "values.yaml").read_text()


def test_scaffold_replaces_a_real_file_squatting_on_a_symlink(repo: Path) -> None:
    folder = repo / "services" / "bl21i-va-ioc-09"
    folder.mkdir(parents=True)
    (folder / "Chart.yaml").write_text("a real file, not a link\n")
    (folder / "templates").mkdir()
    (folder / "templates" / "junk.yaml").write_text("junk\n")

    scaffold(repo, "bl21i-va-ioc-09", fastcs=False, dry_run=False)

    assert (folder / "Chart.yaml").is_symlink()
    assert (folder / "templates").is_symlink()
    assert (repo / ".helm-shared" / "templates" / "ioc_instance.yaml").is_file()


# --- the legacy dev-c7 rule --------------------------------------------------


def test_is_legacy_detects_both_signals(repo: Path) -> None:
    folder = _make_legacy(repo, "bl21i-va-ioc-02")
    assert is_legacy(folder)

    # values.yaml alone is enough
    (folder / "Chart.yaml").unlink()
    assert is_legacy(folder)


def test_is_legacy_ignores_a_dev_c7_image_tag(repo: Path) -> None:
    """``bl21i-ea-ioc-01-debug`` is an ibek IOC whose image tag says dev-c7."""
    folder = repo / "services" / "bl21i-ea-ioc-01-debug"
    folder.mkdir(parents=True)
    _link(folder, "Chart.yaml", "../../.helm-shared/Chart.yaml")
    (folder / "values.yaml").write_text(DEV_C7_IMAGE_VALUES)

    assert "dev-c7" in (folder / "values.yaml").read_text()
    assert not is_legacy(folder)


def test_is_legacy_false_for_a_missing_folder(repo: Path) -> None:
    assert not is_legacy(repo / "services" / "nope")


def test_legacy_folder_is_deleted_and_recreated(repo: Path) -> None:
    folder = _make_legacy(repo, "bl21i-va-ioc-02")
    (folder / "leftover.yaml").write_text("stale\n")

    scaffold(repo, "bl21i-va-ioc-02", fastcs=False, dry_run=False)

    assert not (folder / "leftover.yaml").exists()
    assert os.readlink(folder / "Chart.yaml") == "../../.helm-shared/Chart.yaml"
    assert (folder / "values.yaml").read_text() == IOC_TEMPLATE_VALUES
    assert (folder / "config" / "ioc.yaml").is_file()


def test_deleting_a_legacy_folder_does_not_follow_the_templates_symlink(
    repo: Path,
) -> None:
    """The nightmare case: rmtree descending ``templates`` into .helm-shared."""
    folder = _make_legacy(repo, "bl21i-va-ioc-02")
    # a legacy folder with a stray templates symlink (belt and braces)
    _link(folder, "templates", "../../.helm-shared/templates")
    shared_file = repo / ".helm-shared" / "templates" / "ioc_instance.yaml"
    assert shared_file.is_file()

    scaffold(repo, "bl21i-va-ioc-02", fastcs=False, dry_run=False)

    assert shared_file.is_file()
    assert (repo / ".helm-shared" / "Chart.yaml").is_file()
    assert (repo / ".helm-shared" / "LegacyChart.yaml").is_file()


def test_legacy_folder_is_untouched_on_a_dry_run(repo: Path) -> None:
    folder = _make_legacy(repo, "bl21i-va-ioc-02")
    scaffold(repo, "bl21i-va-ioc-02", fastcs=False, dry_run=True)
    assert (folder / "values.yaml").read_text() == LEGACY_VALUES


# --- write_catio_ioc ---------------------------------------------------------


def test_write_catio_ioc_layout(repo: Path, chain: Chain) -> None:
    write_catio_ioc(repo, chain, dry_run=False)
    folder = repo / "services" / "bl21i-va-catio-01"

    assert sorted(p.name for p in folder.iterdir()) == [
        "Chart.yaml",
        "config",
        "templates",
        "values.yaml",
    ]
    assert sorted(p.name for p in (folder / "config").iterdir()) == ["fastcs.yaml"]


def test_write_catio_ioc_removes_the_example_controller_yaml(
    repo: Path, chain: Chain
) -> None:
    write_catio_ioc(repo, chain, dry_run=False)
    config = repo / "services" / "bl21i-va-catio-01" / "config"
    assert (config / "fastcs.yaml").is_file()
    assert not (config / "controller.yaml").exists()


def test_write_catio_ioc_name_mappings_come_from_the_chain(
    repo: Path, chain: Chain
) -> None:
    write_catio_ioc(repo, chain, dry_run=False)
    doc = _load(repo / "services" / "bl21i-va-catio-01" / "config" / "fastcs.yaml")

    (controller,) = doc["controllers"]
    assert controller["id"] == "BL21I-VA-CATIO-01"
    assert controller["type"] == CATIO_CONTROLLER_TYPE
    assert controller["name_mappings"] == chain.name_mappings()
    assert controller["tcp_settings"]["target_port"] == 27905
    assert controller["route"] == {
        "route_name": "",
        "user_name": "Administrator",
        "password": "1",
    }
    assert controller["scan_timings"] == {
        "poll_period": 1.0,
        "notification_period": 0.2,
    }
    (transport,) = doc["transport"]
    assert transport["epicsca"] == {}
    assert transport["gui"]["output_dir"] == "./screens"
    assert "BL21I-VA-IOC-01" in transport["gui"]["title"]


def test_write_catio_ioc_node_prefix_is_not_a_re_derivation(repo: Path) -> None:
    """A second chain must get its own ordinal, straight from the Chain."""
    chain = Chain(scanner_ioc="BL21I-DI-IOC-01", domain="BL21I-DI", ordinal=3)
    write_catio_ioc(repo, chain, dry_run=False)
    doc = _load(repo / "services" / "bl21i-di-catio-01" / "config" / "fastcs.yaml")
    mappings = doc["controllers"][0]["name_mappings"]
    assert mappings["node_prefix"] == "BL21I-DI-E3RIO-{:02d}"
    assert mappings["node_prefix"] == chain.node_prefix
    assert mappings["device_prefix"] == chain.device_prefix
    assert mappings["module_prefix"] == chain.module_prefix


def test_write_catio_ioc_values_yaml(repo: Path, chain: Chain) -> None:
    write_catio_ioc(repo, chain, dry_run=False)
    text = (repo / "services" / "bl21i-va-catio-01" / "values.yaml").read_text()

    assert text.startswith(
        "# yaml-language-server: $schema=../../.helm-shared/values.schema.json\n"
    )
    assert "stdio-expose --ptty --stdin --ctrl-d" in text
    assert "stdio-socket" not in text
    assert "fastcs-catio run /epics/ioc/config/fastcs.yaml" in text

    doc = YAML(typ="safe").load(text)
    assert set(doc) == {"ioc-instance"}
    instance = doc["ioc-instance"]
    assert instance["image"].startswith("ghcr.io/diamondlightsource/fastcs-catio:")
    assert instance["livenessExecutable"] == ""
    assert instance["preStopExecutable"] == ""
    assert len(instance["args"]) == 1


def test_write_catio_ioc_returns_its_placeholders(repo: Path, chain: Chain) -> None:
    placeholders = write_catio_ioc(repo, chain, dry_run=False)
    assert placeholders == ["REPLACE_WITH_ADS_SERVER_IP", "REPLACE_WITH_PINNED_TAG"]

    written = "".join(
        p.read_text()
        for p in sorted((repo / "services" / "bl21i-va-catio-01").rglob("*.yaml"))
        if p.is_file() and not p.is_symlink()
    )
    for placeholder in placeholders:
        assert placeholder in written


def test_write_catio_ioc_dry_run_writes_nothing(repo: Path, chain: Chain) -> None:
    before = sorted(p.name for p in (repo / "services").iterdir())

    placeholders = write_catio_ioc(repo, chain, dry_run=True)

    assert placeholders == ["REPLACE_WITH_ADS_SERVER_IP", "REPLACE_WITH_PINNED_TAG"]
    assert not (repo / "services" / "bl21i-va-catio-01").exists()
    assert sorted(p.name for p in (repo / "services").iterdir()) == before


def test_write_catio_ioc_is_idempotent(repo: Path, chain: Chain) -> None:
    first = write_catio_ioc(repo, chain, dry_run=False)
    folder = repo / "services" / "bl21i-va-catio-01"
    text = (folder / "config" / "fastcs.yaml").read_text()

    second = write_catio_ioc(repo, chain, dry_run=False)

    assert first == second
    assert (folder / "config" / "fastcs.yaml").read_text() == text
    assert not (folder / "config" / "controller.yaml").exists()


def test_write_catio_ioc_replaces_a_legacy_folder(repo: Path, chain: Chain) -> None:
    folder = _make_legacy(repo, "bl21i-va-catio-01")
    (folder / "values.yaml").write_text(LEGACY_VALUES)

    write_catio_ioc(repo, chain, dry_run=False)

    assert "dev-c7" not in (folder / "values.yaml").read_text()
    assert os.readlink(folder / "Chart.yaml") == "../../.helm-shared/Chart.yaml"


# --- read_sticky_ordinals ----------------------------------------------------


def test_sticky_ordinals_round_trip(repo: Path) -> None:
    """The stickiness loop: what we write is what we read back."""
    chains = [
        Chain(scanner_ioc="BL21I-VA-IOC-01", domain="BL21I-VA", ordinal=1),
        Chain(scanner_ioc="BL21I-VA-IOC-05", domain="BL21I-VA", ordinal=2),
        Chain(scanner_ioc="BL21I-DI-IOC-01", domain="BL21I-DI", ordinal=1),
    ]
    for one in chains:
        write_catio_ioc(repo, one, dry_run=False)

    assert read_sticky_ordinals(repo) == {
        "BL21I-VA-CATIO-01": 1,
        "BL21I-VA-CATIO-05": 2,
        "BL21I-DI-CATIO-01": 1,
    }


def test_sticky_ordinals_survive_double_digits(repo: Path) -> None:
    write_catio_ioc(
        repo,
        Chain(scanner_ioc="BL21I-VA-IOC-01", domain="BL21I-VA", ordinal=12),
        dry_run=False,
    )
    assert read_sticky_ordinals(repo) == {"BL21I-VA-CATIO-01": 12}


def test_sticky_ordinals_empty_repo(repo: Path) -> None:
    assert read_sticky_ordinals(repo) == {}


def test_sticky_ordinals_missing_services_dir(tmp_path: Path) -> None:
    assert read_sticky_ordinals(tmp_path) == {}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("this: [is not: valid yaml\n", id="unparseable"),
        pytest.param("", id="empty"),
        pytest.param("- a\n- list\n", id="not-a-mapping"),
        pytest.param("controllers: not-a-list\n", id="controllers-not-a-list"),
        pytest.param("controllers:\n  - just-a-string\n", id="entry-not-a-mapping"),
        pytest.param(
            "controller:\n  serial_settings:\n    port: /dev/ttyUSB0\n",
            id="singular-controller-mapping",
        ),
        pytest.param(
            "controllers:\n"
            "  - id: BL01C-EA-OTHER-01\n"
            "    type: fastcs_other.Controller\n"
            "    name_mappings:\n"
            '      node_prefix: "X-E9RIO-{:02d}"\n',
            id="another-fastcs-project",
        ),
        pytest.param(
            f"controllers:\n"
            f"  - id: BL21I-VA-CATIO-01\n"
            f"    type: {CATIO_CONTROLLER_TYPE}\n",
            id="no-name-mappings",
        ),
        pytest.param(
            f"controllers:\n"
            f"  - id: BL21I-VA-CATIO-01\n"
            f"    type: {CATIO_CONTROLLER_TYPE}\n"
            f"    name_mappings:\n"
            f'      node_prefix: "BL21I-VA-RIO-{{:02d}}"\n',
            id="node-prefix-without-an-ordinal",
        ),
        pytest.param(
            f"controllers:\n"
            f"  - type: {CATIO_CONTROLLER_TYPE}\n"
            f"    name_mappings:\n"
            f'      node_prefix: "BL21I-VA-E1RIO-{{:02d}}"\n',
            id="no-id",
        ),
    ],
)
def test_sticky_ordinals_tolerates_junk(repo: Path, text: str) -> None:
    junk = repo / "services" / "bl01c-ea-other-01" / "config"
    junk.mkdir(parents=True)
    (junk / "fastcs.yaml").write_text(text)

    good = Chain(scanner_ioc="BL21I-VA-IOC-01", domain="BL21I-VA", ordinal=4)
    write_catio_ioc(repo, good, dry_run=False)

    assert read_sticky_ordinals(repo) == {"BL21I-VA-CATIO-01": 4}


def test_sticky_ordinals_ignores_controller_yaml(repo: Path) -> None:
    """A FastCS IOC using the other config filename is not our business."""
    other = repo / "services" / "bl01c-mo-ppanda-01" / "config"
    other.mkdir(parents=True)
    (other / "controller.yaml").write_text(
        f"controllers:\n"
        f"  - id: SOMETHING-CATIO-99\n"
        f"    type: {CATIO_CONTROLLER_TYPE}\n"
        f"    name_mappings:\n"
        f'      node_prefix: "X-E7RIO-{{:02d}}"\n'
    )
    assert read_sticky_ordinals(repo) == {}


# --- write_ioc ---------------------------------------------------------------


def _ioc(description: str = "an IOC") -> Generic_IOC:
    return Generic_IOC(
        ioc_name="{{ _global.get_env('IOC_NAME') }}",
        description=description,
        entities=[
            {"type": "epics.EpicsEnvSet", "name": "EPICS_TZ", "value": "GMT0BST"}
        ],
        source_file=Path("BL21I-VA-IOC-02.xml"),
    )


def test_write_ioc_layout_and_schema(repo: Path) -> None:
    folder = write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=False)

    assert folder == repo / "services" / "bl21i-va-ioc-02"
    assert (folder / "Chart.yaml").is_symlink()
    assert (folder / "templates").is_symlink()

    text = (folder / "config" / "ioc.yaml").read_text()
    assert text.startswith(f"# yaml-language-server: $schema={IOC_SCHEMA}\n")

    doc = YAML(typ="safe").load(text)
    assert doc["description"] == "an IOC"
    assert doc["entities"][0]["type"] == "epics.EpicsEnvSet"
    assert "source_file" not in doc


def test_write_ioc_leaves_the_image_placeholder(repo: Path) -> None:
    folder = write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=False)
    values = (folder / "values.yaml").read_text()
    for placeholder in IBEK_PLACEHOLDERS:
        assert placeholder in values


def test_write_ioc_keeps_a_pinned_image(repo: Path) -> None:
    folder = repo / "services" / "bl21i-va-ioc-02"
    folder.mkdir(parents=True)
    (folder / "values.yaml").write_text("ioc-instance:\n  image: real:1.2.3\n")

    write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=False)

    assert "real:1.2.3" in (folder / "values.yaml").read_text()


def test_write_ioc_replaces_a_legacy_folder(repo: Path) -> None:
    folder = _make_legacy(repo, "bl21i-va-ioc-02")

    write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=False)

    assert "dev-c7" not in (folder / "values.yaml").read_text()
    assert os.readlink(folder / "Chart.yaml") == "../../.helm-shared/Chart.yaml"
    assert (folder / "config" / "ioc.yaml").is_file()


def test_write_ioc_fills_an_empty_description(repo: Path) -> None:
    ioc = _ioc(description="")
    folder = write_ioc(repo, "BL21I-VA-IOC-02", ioc, dry_run=False)
    doc = YAML(typ="safe").load(folder / "config" / "ioc.yaml")
    assert doc["description"] == "BL21I-VA-IOC-02, converted by builder2ibek catio"


def test_write_ioc_does_not_write_ioc_schema_json(repo: Path) -> None:
    """``ibek pattern schema`` generates that, from a pre-commit hook."""
    folder = write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=False)
    assert not (folder / "ioc.schema.json").exists()


def test_write_ioc_dry_run_writes_nothing(repo: Path) -> None:
    before = sorted(p.name for p in (repo / "services").iterdir())

    folder = write_ioc(repo, "BL21I-VA-IOC-02", _ioc(), dry_run=True)

    assert folder == repo / "services" / "bl21i-va-ioc-02"
    assert not folder.exists()
    assert sorted(p.name for p in (repo / "services").iterdir()) == before
