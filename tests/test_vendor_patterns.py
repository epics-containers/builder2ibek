"""Vendoring the runtime patterns of a pattern-only IOC into its instance."""

from pathlib import Path

import pytest
from ibek.pattern_cmds.schema import SCHEMA_HEADER
from typer.testing import CliRunner

from builder2ibek.__main__ import cli
from builder2ibek.patterns import pattern_index
from builder2ibek.vendor_patterns import (
    DEFAULT_RUNTIME_IMAGE,
    instance_folder,
    vendor_patterns,
)
from tests.conftest import SCHEMA_CACHE

SAMPLES = Path(__file__).parent / "samples"

ATTOCUBE = pattern_index().patterns["attocubeInterf"].ref
DEFAULT_HEADER = "# yaml-language-server: $schema=/epics/ibek-defs/ioc.schema.json"


def _entities(*extra: dict) -> list[dict]:
    return [
        {"type": "epics.EpicsEnvSet", "name": "EPICS_TZ", "value": "GMT0BST"},
        {"type": "devIocStats.iocAdminSoft", "IOC": "X"},
        {"type": "asyn.AsynIP", "name": "p1", "port": "127.0.0.1:9090"},
        {"type": "attocubeInterf.ids3010", "P": "X-", "Q": "01", "PORT": "p1"},
        *extra,
    ]


def _instance(tmp_path: Path, image: str | None = DEFAULT_RUNTIME_IMAGE) -> Path:
    """An instance with an ioc.yaml as xml2yaml writes it, before vendoring."""
    instance = tmp_path / "bl08j-mo-ioc-13"
    (instance / "config").mkdir(parents=True)
    (instance / "config" / "ioc.yaml").write_text(f"{DEFAULT_HEADER}\nentities: []\n")
    values = f"ioc-instance:\n  image: {image or 'REPLACE_WITH_IMAGE_URI'}\n"
    (instance / "values.yaml").write_text(values)
    return instance


def _header(instance: Path) -> str:
    return (instance / "config" / "ioc.yaml").read_text().partition("\n")[0]


def test_default_image_has_a_cached_schema():
    """Bumping DEFAULT_RUNTIME_IMAGE needs the new image's base schema in the
    fixture cache, or every pattern test would need the network."""
    repo, _, tag = DEFAULT_RUNTIME_IMAGE.rpartition(":")
    host, _, path = repo.partition("/")
    cached = SCHEMA_CACHE / host / path.removesuffix("-runtime") / f"{tag}.json"
    assert cached.is_file(), f"no cached base schema {cached}"


def test_instance_folder(tmp_path: Path):
    assert instance_folder(tmp_path / "a" / "config" / "ioc.yaml") == tmp_path / "a"
    assert instance_folder(tmp_path / "a" / "ioc.yaml") is None


def test_pattern_only_ioc_is_vendored(tmp_path: Path):
    instance = _instance(tmp_path)
    result = vendor_patterns(_entities(), instance / "config" / "ioc.yaml")
    assert result.refs == [ATTOCUBE]
    assert result.image == DEFAULT_RUNTIME_IMAGE
    assert result.vendored and result.warnings == []
    assert f"vendored {ATTOCUBE} into {instance}" in result.notes
    assert (instance / "config" / "attocubeInterf.ibek.support.yaml").is_file()
    assert (instance / "runtime-lock.yaml").is_file()
    assert (instance / "ioc.schema.json").is_file()
    assert _header(instance) == SCHEMA_HEADER


def test_vendoring_again_changes_nothing(tmp_path: Path):
    instance = _instance(tmp_path)
    ioc_yaml = instance / "config" / "ioc.yaml"
    vendor_patterns(_entities(), ioc_yaml)
    files = {p: p.read_bytes() for p in instance.rglob("*") if p.is_file()}
    # a reconversion writes the ioc.yaml with the default header again first
    ioc_yaml.write_text(f"{DEFAULT_HEADER}\nentities: []\n")
    result = vendor_patterns(_entities(), ioc_yaml)
    assert result.vendored and result.warnings == []
    assert {p: p.read_bytes() for p in instance.rglob("*") if p.is_file()} == files


def test_no_vendor_lists_the_patterns_only(tmp_path: Path):
    instance = _instance(tmp_path)
    result = vendor_patterns(
        _entities(), instance / "config" / "ioc.yaml", vendor=False
    )
    assert result.refs == [ATTOCUBE] and not result.vendored
    assert not (instance / "runtime-lock.yaml").exists()
    assert _header(instance) == DEFAULT_HEADER


def test_ioc_yaml_outside_an_instance(tmp_path: Path):
    ioc_yaml = tmp_path / "ioc.yaml"
    ioc_yaml.write_text("entities: []\n")
    result = vendor_patterns(_entities(), ioc_yaml)
    assert result.refs == [ATTOCUBE] and not result.vendored
    assert "is not in the config/ folder" in result.warnings[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ioc.yaml"]


def test_instance_with_no_image(tmp_path: Path):
    """The files and lock are vendored; the schema waits for the image."""
    instance = _instance(tmp_path, image=None)
    result = vendor_patterns(_entities(), instance / "config" / "ioc.yaml")
    assert result.vendored
    assert (instance / "runtime-lock.yaml").is_file()
    assert not (instance / "ioc.schema.json").exists()
    assert "pins no image" in result.warnings[0]
    assert DEFAULT_RUNTIME_IMAGE in result.warnings[0]


def test_instance_with_another_image(tmp_path: Path):
    instance = _instance(tmp_path, image="ghcr.io/epics-containers/ioc-pmac:1.0")
    result = vendor_patterns(_entities(), instance / "config" / "ioc.yaml")
    assert not result.vendored
    assert "pins image ghcr.io/epics-containers/ioc-pmac:1.0" in result.warnings[0]
    assert not (instance / "runtime-lock.yaml").exists()


def test_mixed_ioc_is_not_vendored(tmp_path: Path):
    instance = _instance(tmp_path)
    brick = {"type": "pmac.GeoBrick", "name": "BRICK1", "PORT": "p1"}
    result = vendor_patterns(_entities(brick), instance / "config" / "ioc.yaml")
    assert result.refs == [] and not result.vendored
    assert "also needs pmac" in result.warnings[0]
    assert ATTOCUBE in result.warnings[0]
    assert not (instance / "runtime-lock.yaml").exists()


def test_rejected_pattern_module_is_reported(tmp_path: Path):
    """A module whose pattern rejects its entities keeps the IOC off the
    runtime image, and the reason is given."""
    instance = _instance(tmp_path)
    no_q = {"type": "attocubeInterf.ids3010", "P": "Y-", "PORT": "p1"}
    scroll = {"type": "EdwardsScroll.EdwardsScroll", "P": "X", "port": "p1"}
    result = vendor_patterns(_entities(no_q, scroll), instance / "config" / "ioc.yaml")
    assert not result.vendored
    warning = result.warnings[0]
    assert "also needs attocubeInterf" in warning
    assert f"attocubeInterf: {ATTOCUBE} rejects" in warning


def test_ioc_without_patterns_is_left_alone(tmp_path: Path):
    instance = _instance(tmp_path)
    result = vendor_patterns(_entities()[:3], instance / "config" / "ioc.yaml")
    assert result.refs == [] and result.warnings == [] and result.notes == []
    assert not (instance / "runtime-lock.yaml").exists()


def test_stale_lock_entry_is_reported(tmp_path: Path):
    instance = _instance(tmp_path)
    ioc_yaml = instance / "config" / "ioc.yaml"
    scroll = {"type": "EdwardsScroll.EdwardsScroll", "P": "X", "port": "p1"}
    vendor_patterns(_entities(scroll), ioc_yaml)
    result = vendor_patterns(_entities(), ioc_yaml)
    assert result.vendored
    assert "also holds EdwardsScroll" in result.warnings[0]


def test_lock_left_when_nothing_is_vendored(tmp_path: Path):
    instance = _instance(tmp_path)
    ioc_yaml = instance / "config" / "ioc.yaml"
    vendor_patterns(_entities(), ioc_yaml)
    result = vendor_patterns(_entities()[:3], ioc_yaml)
    assert "holds attocubeInterf, but nothing was vendored" in result.warnings[0]


@pytest.mark.parametrize("vendor", [True, False])
def test_cli_patterns_out(tmp_path: Path, vendor: bool):
    instance = _instance(tmp_path)
    patterns_out = tmp_path / "patterns"
    args = [
        "xml2yaml",
        str(SAMPLES / "BL08J-MO-IOC-13.xml"),
        "--yaml",
        str(instance / "config" / "ioc.yaml"),
        "--patterns-out",
        str(patterns_out),
    ]
    if not vendor:
        args.append("--no-vendor")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert patterns_out.read_text() == f"{ATTOCUBE}\n"
    assert (f"vendored {ATTOCUBE}" in result.output) == vendor
    assert (instance / "runtime-lock.yaml").exists() == vendor


def test_cli_patterns_out_empty_without_patterns(tmp_path: Path):
    instance = _instance(tmp_path)
    patterns_out = tmp_path / "patterns"
    result = CliRunner().invoke(
        cli,
        [
            "xml2yaml",
            str(SAMPLES / "BL08J-MO-IOC-06.xml"),
            "--yaml",
            str(instance / "config" / "ioc.yaml"),
            "--patterns-out",
            str(patterns_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert patterns_out.read_text() == ""
