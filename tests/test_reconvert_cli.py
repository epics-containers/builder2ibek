"""Tests for builder2ibek.reconvert."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from builder2ibek import reconvert as rc

SAMPLES = Path(__file__).parent / "samples"


def test_normalize_beamline_short_forms():
    assert rc.normalize_beamline("i21") == "BL21I"
    assert rc.normalize_beamline("i04") == "BL04I"
    assert rc.normalize_beamline("b07") == "BL07B"
    assert rc.normalize_beamline("p45") == "BL45P"


def test_normalize_beamline_already_normalized():
    assert rc.normalize_beamline("BL21I") == "BL21I"
    assert rc.normalize_beamline("bl19i") == "BL19I"


def test_normalize_beamline_invalid():
    with pytest.raises(ValueError):
        rc.normalize_beamline("bogus-prefix")


def test_is_template_filename():
    assert rc._is_template_xml(Path("GIGE-FIT-TEMPLATE.xml"))
    assert rc._is_template_xml(Path("ClaspTemplate.xml"))
    assert rc._is_template_xml(Path("$(IOC)-foo.xml"))
    assert not rc._is_template_xml(Path("BL21I-MO-IOC-01.xml"))


def test_read_existing_description(tmp_path: Path):
    ioc_yaml = tmp_path / "ioc.yaml"
    ioc_yaml.write_text("ioc_name: test\ndescription: Cryo cooler\nentities: []\n")
    assert rc._read_existing_description(ioc_yaml) == "Cryo cooler"

    missing = tmp_path / "absent.yaml"
    assert rc._read_existing_description(missing) == ""


def _fake_services_repo(tmp_path: Path, ioc_name: str) -> Path:
    """Create a minimal services repo with a single ioc.yaml."""
    repo = tmp_path / "fake-services"
    cfg = repo / "services" / ioc_name / "config"
    cfg.mkdir(parents=True)
    (cfg / "ioc.yaml").write_text(
        "ioc_name: placeholder\ndescription: Old description\nentities: []\n"
    )
    return repo


def test_run_reconvert_no_matching_services_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    xml = SAMPLES / "BL11I-CS-IOC-09.xml"
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))

    repo = tmp_path / "empty-services"
    (repo / "services").mkdir(parents=True)

    result, code = rc.run_reconvert("i11", repo, validate=False)

    assert code == 0
    assert result.ioc_candidates == []
    assert len(result.skipped) == 1
    assert result.skipped[0]["reason"] == "no-services-folder"
    assert result.reconverted == []


def test_run_reconvert_happy_path_no_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    xml = SAMPLES / "BL11I-CS-IOC-09.xml"
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))

    ioc_name = xml.stem.lower()
    repo = _fake_services_repo(tmp_path, ioc_name)

    result, code = rc.run_reconvert("i11", repo, validate=False)

    assert code == 0
    assert len(result.reconverted) == 1
    assert result.reconverted[0]["ioc_name"] == ioc_name
    assert result.conversion_errors == []
    assert result.validation == []

    rewritten = repo / "services" / ioc_name / "config" / "ioc.yaml"
    text = rewritten.read_text()
    # Existing description should have been preserved through the round-trip.
    assert "Old description" in text
    # And the file should look like a real converted IOC, not the placeholder.
    assert "EPICS_TZ" in text


def test_run_reconvert_only_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    xml = SAMPLES / "BL11I-CS-IOC-09.xml"
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    repo = _fake_services_repo(tmp_path, xml.stem.lower())

    result, code = rc.run_reconvert(
        "i11", repo, validate=False, only=["some-other-ioc"]
    )

    assert code == 0
    assert result.reconverted == []
    reasons = {s["reason"] for s in result.skipped}
    assert "filtered-by-only" in reasons


def test_run_reconvert_bad_beamline_raises(tmp_path: Path):
    (tmp_path / "services").mkdir()
    with pytest.raises(ValueError):
        rc.run_reconvert("not-a-beamline", tmp_path, validate=False)


def test_run_reconvert_missing_services_repo(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        rc.run_reconvert("i11", missing, validate=False)


def test_cli_help():
    cmd = [sys.executable, "-m", "builder2ibek", "reconvert", "--help"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "reconvert" in result.stdout
    assert "--services-repo" in result.stdout
    assert "--no-validate" in result.stdout
