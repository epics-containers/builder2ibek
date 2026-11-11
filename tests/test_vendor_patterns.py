"""Vendoring the runtime patterns of a pattern-only IOC into its instance."""

import json
import shutil
from pathlib import Path

import pytest
from ibek.pattern_cmds.schema import SCHEMA_HEADER, _cache_path
from ruamel.yaml import YAML
from typer.testing import CliRunner

from builder2ibek import vendor_patterns as vp
from builder2ibek.__main__ import cli
from builder2ibek.patterns import PatternIndexError, pattern_index
from builder2ibek.vendor_patterns import (
    DEFAULT_RUNTIME_IMAGE,
    VendorError,
    instance_folder,
    vendor_patterns,
    write_schema_cache,
)

SAMPLES = Path(__file__).parent / "samples"
MO_IOC_13 = SAMPLES / "BL08J-MO-IOC-13.xml"

ATTOCUBE = pattern_index().patterns["attocubeInterf"]
DEFAULT_HEADER = "# yaml-language-server: $schema=/epics/ibek-defs/ioc.schema.json"
RUNTIME_REPO = DEFAULT_RUNTIME_IMAGE.rpartition(":")[0]


def _entities(*extra: dict) -> list[dict]:
    return [
        {"type": "epics.EpicsEnvSet", "name": "EPICS_TZ", "value": "GMT0BST"},
        {"type": "devIocStats.iocAdminSoft", "IOC": "X"},
        {"type": "asyn.AsynIP", "name": "p1", "port": "127.0.0.1:9090"},
        {"type": "attocubeInterf.ids3010", "P": "X-", "Q": "01", "PORT": "p1"},
        *extra,
    ]


def _instance(tmp_path: Path, values: str | None = None) -> Path:
    """An instance with an ioc.yaml as xml2yaml writes it, before vendoring."""
    instance = tmp_path / "bl08j-mo-ioc-13"
    (instance / "config").mkdir(parents=True)
    _reset_header(instance)
    if values is None:
        values = f"ioc-instance:\n  image: {DEFAULT_RUNTIME_IMAGE}\n"
    (instance / "values.yaml").write_text(values)
    return instance


def _reset_header(instance: Path):
    (instance / "config" / "ioc.yaml").write_text(f"{DEFAULT_HEADER}\nentities: []\n")


def _header(instance: Path) -> str:
    return (instance / "config" / "ioc.yaml").read_text().partition("\n")[0]


def _vendor(instance: Path, *extra: dict, **kwargs):
    return vendor_patterns(
        _entities(*extra), instance / "config" / "ioc.yaml", **kwargs
    )


def _files(instance: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in instance.rglob("*") if p.is_file()}


def _lock(instance: Path) -> dict:
    return YAML(typ="safe").load(instance / "runtime-lock.yaml")


# -- the default image's base schema --------------------------------------------


def test_default_image_schema_is_packaged():
    """Bumping DEFAULT_RUNTIME_IMAGE needs the new image's base schema in
    src/builder2ibek/schemas, or classifying an IOC would need the network."""
    assert vp._schema_file(DEFAULT_RUNTIME_IMAGE).is_file()


def test_write_schema_cache_matches_ibek(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IBEK_SCHEMA_CACHE", str(tmp_path))
    write_schema_cache(tmp_path)
    cached = _cache_path(DEFAULT_RUNTIME_IMAGE)
    assert json.loads(cached.read_text()) == vp._base_schema(DEFAULT_RUNTIME_IMAGE)
    validators = json.loads(cached.with_suffix(".validators.json").read_text())
    assert validators["url"].endswith("/2.8.26ec8/ibek.ioc.schema.json")


def test_instance_folder(tmp_path: Path):
    assert instance_folder(tmp_path / "a" / "config" / "ioc.yaml") == tmp_path / "a"
    assert instance_folder(tmp_path / "a" / "ioc.yaml") is None


# -- pattern-only IOCs -----------------------------------------------------------


def test_pattern_only_ioc_is_vendored(tmp_path: Path):
    instance = _instance(tmp_path)
    result = _vendor(instance)
    assert result.refs == [ATTOCUBE.ref]
    assert result.image == DEFAULT_RUNTIME_IMAGE
    assert result.vendored and result.warnings == []
    assert f"vendored {ATTOCUBE.ref} into {instance}" in result.notes
    assert (instance / "config" / "attocubeInterf.ibek.support.yaml").is_file()
    assert (instance / "ioc.schema.json").is_file()
    assert _header(instance) == SCHEMA_HEADER
    # vendored from the submodule, recorded as from GitHub
    entry = _lock(instance)["patterns"]["attocubeInterf"]
    assert entry["source"] == "github.com/epics-containers/ibek-runtime-streamdevice"
    assert entry["version"] == ATTOCUBE.version


def test_vendoring_again_changes_nothing(tmp_path: Path):
    instance = _instance(tmp_path)
    _vendor(instance)
    files = _files(instance)
    _reset_header(instance)
    result = _vendor(instance)
    assert result.vendored and result.warnings == []
    assert f"vendored {ATTOCUBE.ref} into {instance}" not in result.notes
    assert _files(instance) == files


def test_locked_version_is_kept(tmp_path: Path):
    """The services repo's choice of version is not overridden."""
    instance = _instance(tmp_path)
    _vendor(instance)
    lock = instance / "runtime-lock.yaml"
    lock.write_text(
        lock.read_text().replace(f"version: {ATTOCUBE.version}", "version: 0.7.9")
    )
    _reset_header(instance)
    result = _vendor(instance)
    assert _lock(instance)["patterns"]["attocubeInterf"]["version"] == "0.7.9"
    assert any(
        "pins attocubeInterf 0.7.9" in w and ATTOCUBE.version in w
        for w in result.warnings
    )
    assert _header(instance) == SCHEMA_HEADER


def test_locked_files_are_checked(tmp_path: Path):
    instance = _instance(tmp_path)
    _vendor(instance)
    (instance / "config" / "ids3010.proto").write_text("edited\n")
    result = _vendor(instance)
    assert any("ibek pattern check" in w for w in result.warnings)
    assert (instance / "config" / "ids3010.proto").read_text() == "edited\n"


def test_placeholder_image_is_filled(tmp_path: Path):
    values = (
        "# yaml-language-server: $schema=../../.helm-shared/values.schema.json\n\n"
        "ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n\n  # a comment\n"
    )
    instance = _instance(tmp_path, values)
    result = _vendor(instance)
    assert result.vendored and result.warnings == []
    assert (instance / "values.yaml").read_text() == values.replace(
        "REPLACE_WITH_IMAGE_URI", DEFAULT_RUNTIME_IMAGE
    )
    assert (instance / "ioc.schema.json").is_file()
    assert _header(instance) == SCHEMA_HEADER


def test_instance_with_no_image(tmp_path: Path):
    """The files and lock are vendored; the schema waits for an image."""
    instance = _instance(tmp_path, "ioc-instance:\n  startupExecutable: x\n")
    result = _vendor(instance)
    assert result.vendored
    assert not (instance / "ioc.schema.json").exists()
    assert "pins no image" in result.warnings[0]
    assert DEFAULT_RUNTIME_IMAGE in result.warnings[0]


def test_no_schema_from_ibek(tmp_path: Path, monkeypatch):
    """ibek cannot find the image's base schema: no network, empty cache."""
    monkeypatch.setenv("IBEK_SCHEMA_CACHE", str(tmp_path / "empty"))
    instance = _instance(tmp_path)
    result = _vendor(instance)
    assert result.vendored
    assert "ibek wrote no ioc.schema.json" in result.warnings[0]
    assert _header(instance) == DEFAULT_HEADER


def test_another_tag_of_the_runtime_image(tmp_path: Path, monkeypatch):
    """Classified against the base schema of the tag the instance pins."""
    other = f"{RUNTIME_REPO}:2.8.26ec7"
    cache = tmp_path / "cache"
    write_schema_cache(cache)
    monkeypatch.setenv("IBEK_SCHEMA_CACHE", str(cache))
    ec8 = _cache_path(DEFAULT_RUNTIME_IMAGE)
    shutil.copy(ec8, ec8.with_name("2.8.26ec7.json"))
    validators = ec8.with_suffix(".validators.json").read_text()
    ec8.with_name("2.8.26ec7.validators.json").write_text(
        validators.replace("2.8.26ec8", "2.8.26ec7")
    )
    instance = _instance(tmp_path, f"ioc-instance:\n  image: {other}\n")
    result = _vendor(instance)
    assert result.vendored and result.image == other
    assert result.warnings == []


def test_schema_not_found(tmp_path: Path, monkeypatch):
    """A tag whose base schema is neither packaged nor cached, offline."""
    monkeypatch.setenv("IBEK_SCHEMA_CACHE", str(tmp_path / "empty"))
    instance = _instance(tmp_path, f"ioc-instance:\n  image: {RUNTIME_REPO}:9.9.9ec1\n")
    result = _vendor(instance)
    assert not result.vendored and not result.decided
    assert "cannot tell which modules" in result.warnings[0]
    assert "switch" not in result.warnings[0]
    assert not (instance / "runtime-lock.yaml").exists()


# -- IOCs that are not vendored ---------------------------------------------------


def test_no_vendor_lists_the_patterns_only(tmp_path: Path):
    instance = _instance(tmp_path)
    result = _vendor(instance, vendor=False)
    assert result.refs == [ATTOCUBE.ref] and not result.vendored
    assert not (instance / "runtime-lock.yaml").exists()
    assert _header(instance) == DEFAULT_HEADER


def test_ioc_yaml_outside_an_instance(tmp_path: Path):
    ioc_yaml = tmp_path / "ioc.yaml"
    ioc_yaml.write_text("entities: []\n")
    result = vendor_patterns(_entities(), ioc_yaml)
    assert result.refs == [ATTOCUBE.ref] and not result.vendored
    assert "is not in the config/ folder" in result.warnings[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ioc.yaml"]


def test_instance_with_another_image(tmp_path: Path):
    instance = _instance(tmp_path, "ioc-instance:\n  image: ghcr.io/x/ioc-pmac:1.0\n")
    result = _vendor(instance)
    assert not result.vendored and not result.decided
    assert "pins image ghcr.io/x/ioc-pmac:1.0" in result.warnings[0]
    assert not (instance / "runtime-lock.yaml").exists()


def test_mixed_ioc_is_not_vendored(tmp_path: Path):
    instance = _instance(tmp_path)
    brick = {"type": "pmac.GeoBrick", "name": "BRICK1", "PORT": "p1"}
    result = _vendor(instance, brick)
    assert result.refs == [] and not result.vendored
    assert "also needs pmac" in result.warnings[0]
    assert ATTOCUBE.ref in result.warnings[0]
    assert not (instance / "runtime-lock.yaml").exists()


def test_rejected_pattern_module_is_reported(tmp_path: Path):
    """A module whose pattern rejects its entities keeps the IOC off the
    runtime image, and the reason is given."""
    instance = _instance(tmp_path)
    no_q = {"type": "attocubeInterf.ids3010", "P": "Y-", "PORT": "p1"}
    scroll = {"type": "EdwardsScroll.EdwardsScroll", "P": "X", "port": "p1"}
    result = _vendor(instance, no_q, scroll)
    assert not result.vendored
    warning = result.warnings[0]
    assert "also needs attocubeInterf" in warning
    assert f"attocubeInterf: {ATTOCUBE.ref} rejects" in warning


def test_ioc_without_patterns_is_left_alone(tmp_path: Path):
    instance = _instance(tmp_path)
    result = vendor_patterns(_entities()[:3], instance / "config" / "ioc.yaml")
    assert result.refs == [] and result.warnings == [] and result.notes == []
    assert not (instance / "runtime-lock.yaml").exists()


# -- an instance that already has a runtime-lock.yaml ----------------------------


def test_stale_lock_entry_is_reported(tmp_path: Path):
    instance = _instance(tmp_path)
    scroll = {"type": "EdwardsScroll.EdwardsScroll", "P": "X", "port": "p1"}
    _vendor(instance, scroll)
    result = _vendor(instance)
    assert result.vendored
    assert "also holds EdwardsScroll" in result.warnings[0]


def test_lock_left_when_the_ioc_is_no_longer_pattern_only(tmp_path: Path):
    instance = _instance(tmp_path)
    _vendor(instance)
    brick = {"type": "pmac.GeoBrick", "name": "BRICK1", "PORT": "p1"}
    result = _vendor(instance, brick)
    assert (
        "holds attocubeInterf, and this IOC is not pattern-only"
        in (result.warnings[-1])
    )


@pytest.mark.parametrize(
    "values", ["ioc-instance:\n  image: ghcr.io/x/ioc-pmac:1.0\n", None]
)
def test_undecided_leaves_the_lock_alone(tmp_path: Path, values):
    """Another image, or --no-vendor: the lock is not judged, nor touched."""
    instance = _instance(tmp_path)
    _vendor(instance)
    lock = (instance / "runtime-lock.yaml").read_text()
    if values:
        (instance / "values.yaml").write_text(values)
    result = _vendor(instance, vendor=values is not None)
    assert not result.decided
    assert any(n.startswith("patterns not considered;") for n in result.notes)
    assert not any("holds" in w for w in result.warnings)
    assert (instance / "runtime-lock.yaml").read_text() == lock


def test_index_error_is_reported_once(tmp_path: Path, monkeypatch):
    def broken():
        raise PatternIndexError("offline")

    monkeypatch.setattr(vp, "pattern_index", broken)
    monkeypatch.setattr(vp, "_index_warned", False)
    instance = _instance(tmp_path)
    first = _vendor(instance)
    second = _vendor(instance)
    assert first.warnings == ["runtime patterns not considered: offline"]
    assert second.warnings == []
    assert not first.decided


# -- through xml2yaml and convert_file ------------------------------------------


def _xml2yaml(instance: Path, *args: str):
    return CliRunner().invoke(
        cli,
        [
            "xml2yaml",
            str(MO_IOC_13),
            "--yaml",
            str(instance / "config" / "ioc.yaml"),
            *args,
        ],
    )


@pytest.mark.parametrize("vendor", [True, False])
def test_cli_patterns_out(tmp_path: Path, vendor: bool):
    instance = _instance(tmp_path)
    patterns_out = tmp_path / "patterns"
    args = ["--patterns-out", str(patterns_out)] + ([] if vendor else ["--no-vendor"])
    result = _xml2yaml(instance, *args)
    assert result.exit_code == 0, result.output
    assert patterns_out.read_text() == f"{ATTOCUBE.ref}\n"
    assert (f"vendored {ATTOCUBE.ref}" in result.output) == vendor
    assert (instance / "runtime-lock.yaml").exists() == vendor
    # ibek's own reports stay out of xml2yaml's output
    assert "Using cached schema" not in result.output


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


def test_cli_no_vendor_keeps_the_instance_header(tmp_path: Path):
    instance = _instance(tmp_path)
    assert _xml2yaml(instance).exit_code == 0
    files = _files(instance)
    result = _xml2yaml(instance, "--no-vendor")
    assert result.exit_code == 0, result.output
    assert _header(instance) == SCHEMA_HEADER
    assert "runtime-lock.yaml left as is" in result.output
    assert _files(instance) == files


def test_cli_vendor_error_exits_1(tmp_path: Path, monkeypatch):
    def fail(*_args):
        raise VendorError("ibek pattern add failed")

    monkeypatch.setattr(vp, "_vendor", fail)
    result = _xml2yaml(_instance(tmp_path))
    assert result.exit_code == 1
    assert "ibek pattern add failed" in result.output
