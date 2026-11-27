"""Tests for builder2ibek hardware-status."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from builder2ibek.__main__ import cli

FIXTURE = Path(__file__).parent / "hardware_status" / "services-repo"
SCREEN = Path("synoptic") / "hardware-status"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "services-repo"
    shutil.copytree(FIXTURE, dest)
    return dest


def run(repo: Path) -> ET.Element:
    result = CliRunner().invoke(cli, ["hardware-status", str(repo)])
    assert result.exit_code == 0, result.output
    assert "4 IOCs, 3 devices" in result.output
    return ET.parse(repo / SCREEN / "hardware-status.bob").getroot()


def groups(root: ET.Element) -> dict[str, ET.Element]:
    return {g.findtext("name", ""): g for g in root.findall("widget[@type='group']")}


def test_ioc_rows(repo: Path):
    root = run(repo)
    assert root.findtext("name") == "B99 Hardware Status"
    iocs = groups(root)["IOCs"]

    # ibek IOCs are buttons to their published screens
    buttons = {
        b.findtext("text"): b.findtext("actions/action/file")
        for b in iocs.findall("widget[@type='action_button']")
    }
    assert buttons == {
        "BL99X-MO-IOC-01": "../../bl99x-mo-ioc-01/index.bob",
        "BL99X-VA-IOC-01": "../../bl99x-va-ioc-01/index.bob",
    }
    texts = [w.findtext("text") for w in iocs.findall("widget[@type='label']")]
    # dev-c7 and external IOCs are labels; the skipped service, the other
    # beamline's and the duplicate external entry are left out
    assert texts.count("BL99X-EA-IOC-01") == 1
    assert texts.count("BL99X-DI-IOC-01") == 1
    assert "BL88Y-MO-IOC-01" not in texts and "BL99X-SYNOPTIC" not in texts
    assert "BL99X-MO-IOC-01" not in texts  # a button, not an external label
    for kind in ("ibek", "dev-c7", "vxWorks VME crate", "Motion", "Endstation"):
        assert kind in texts

    pvs = {w.findtext("pv_name") for w in iocs.iter("widget")} - {None}
    assert pvs == {
        "BL99X-MO-IOC-01:IOC_CPU_LOAD.SEVR",
        "BL99X-MO-IOC-01:UPTIME",
        "BL99X-MO-IOC-01:SR_status.SEVR",
        "BL99X-VA-IOC-01:IOC_CPU_LOAD.SEVR",
        "BL99X-VA-IOC-01:UPTIME",
        "BL99X-EA-IOC-01:LOAD.SEVR",
        "BL99X-EA-IOC-01:UPTIME",
        "BL99X-DI-IOC-01:LOAD.SEVR",
        "BL99X-DI-IOC-01:UPTIME",
    }


def test_device_panels(repo: Path):
    root = run(repo)
    panels = groups(root)
    assert list(panels) == ["IOCs", "GeoBricks", "PLCs"]

    bricks = {w.findtext("pv_name") for w in panels["GeoBricks"].iter("widget")}
    assert bricks - {None} == {
        "BL99X-MO-BRICK-01:CPULOAD_0.SEVR",
        "BL99X-MO-BRICK-01:MOTIONSTOP:RBV",
        "BL99X-MO-BRICK-01:MOTIONSTOP_ACTIVE:RBV",
        "BL99X-MO-BRICK-02:CPULOAD_0.SEVR",
    }
    plc = panels["PLCs"]
    assert plc.find("widget[@type='textupdate']/pv_name").text == (  # type: ignore[union-attr]
        "BL99X-VA-PLC-01:MODE"
    )
    assert plc.find("widget[@type='action_button']/actions/action/file").text == (  # type: ignore[union-attr]
        "../../bl99x-va-ioc-01/index.bob"
    )


def test_opis_root(repo: Path):
    config = repo / SCREEN / "hardware-status.yaml"
    config.write_text(config.read_text() + "opis_root: ../../..\n")
    root = run(repo)
    files = {f.text for f in root.iter("file")}
    assert "../../../bl99x-mo-ioc-01/index.bob" in files


def test_missing_config(tmp_path: Path):
    result = CliRunner().invoke(cli, ["hardware-status", str(tmp_path)])
    assert result.exit_code == 1
    assert "hardware-status.yaml not found" in result.output
