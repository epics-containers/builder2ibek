"""
Tests for the won't-convert mechanism.

builder2ibek leaves procServControl and adPython entities out of the ioc.yaml,
with one warning per entity type per IOC naming the IOC, the entity type and
the reason. For adPython the warning also names the entities that reference
the dropped plugin's port.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from builder2ibek import reconvert as rc
from builder2ibek.convert import convert_file

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <ADAravis.aravisCamera CLASS="AVT_Manta_G235C" ID="127.0.0.1"
    P="BL01C-DI-CAM-01" PORT="CAM1.CAM" R=":CAM:"/>
  <adPython.adPythonPlugin ADDR="0" NDARRAY_PORT="CAM1.CAM"
    P="BL01C-DI-CAM-01" PORT="CAM1.ROT" R=":ROT:" TIMEOUT="1"
    classname="Rotate"/>
  <adPython.adPythonPlugin ADDR="0" NDARRAY_PORT="CAM1.CAM"
    P="BL01C-DI-CAM-01" PORT="CAM1.MXSC" R=":MXSC:" TIMEOUT="1"
    classname="MxSampleDetect"/>
  <ADCore.NDROI ADDR="0" NDARRAY_PORT="CAM1.ROT" P="BL01C-DI-CAM-01"
    PORT="CAM1.ROI" R=":ROI:" TIMEOUT="1"/>
  <procServControl.procServControl DESCRIPTION="Camserver control"
    MANUALSTART="#" P="BL01C-EA-DET-01:PSC" PORT="BL01C-EA-DET-01"
    name="CAMSERVER1"/>
  <procServControl.procServControlGui P="BL01C-DI-IOC-01" name="IOC"/>
  <procServControl.procServControlGui P="BL01C-EA-MALC-01" name="MALC"/>
</components>
"""

IOC = "BL01C-DI-IOC-01"


def _write_xml(folder: Path) -> Path:
    xml = folder / f"{IOC}.xml"
    xml.write_text(XML)
    return xml


def _convert(tmp_path: Path) -> tuple[list[dict], list[str]]:
    xml = _write_xml(tmp_path)
    yaml = tmp_path / "ioc.yaml"
    warnings = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json").warnings
    return YAML(typ="safe").load(yaml.read_text())["entities"], warnings


def test_entities_left_out(tmp_path: Path):
    entities, _ = _convert(tmp_path)
    types = [e["type"] for e in entities]
    assert not [t for t in types if t.startswith(("adPython.", "procServControl."))]
    # the rest of the IOC still converts
    assert "ADAravis.aravisCamera" in types
    assert "ADCore.NDROI" in types


def test_one_warning_per_entity_type(tmp_path: Path):
    _, warnings = _convert(tmp_path)
    assert len(warnings) == 3
    by_type = {
        t: [w for w in warnings if f" {t} " in w]
        for t in (
            "adPython.adPythonPlugin",
            "procServControl.procServControl",
            "procServControl.procServControlGui",
        )
    }
    assert all(len(w) == 1 for w in by_type.values())
    for warning in warnings:
        assert warning.startswith(f"{IOC}: won't convert ")

    (gui,) = by_type["procServControl.procServControlGui"]
    assert "won't convert 2 " in gui
    assert "Kubernetes and argocd-monitor replace it" in gui

    (adpython,) = by_type["adPython.adPythonPlugin"]
    assert "won't convert 2 " in adpython
    assert "ADExternal" in adpython
    assert "builder2ibek/issues/173" in adpython


def test_adpython_names_downstream_references(tmp_path: Path):
    _, warnings = _convert(tmp_path)
    (adpython,) = [w for w in warnings if "adPython" in w]
    assert "port CAM1.ROT is still referenced by: ADCore.NDROI NDARRAY_PORT" in (
        adpython
    )
    assert "port CAM1.MXSC: nothing else in the IOC references it" in adpython


def test_xml2yaml_prints_warnings(tmp_path: Path):
    xml = _write_xml(tmp_path)
    cmd = [
        sys.executable,
        "-m",
        "builder2ibek",
        "xml2yaml",
        str(xml),
        "--yaml",
        str(tmp_path / "ioc.yaml"),
    ]
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stderr.count(f"warning: {IOC}: won't convert ") == 3


def test_reconvert_summary_includes_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    xml = _write_xml(tmp_path)
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    cfg = tmp_path / "services-repo" / "services" / IOC.lower() / "config"
    cfg.mkdir(parents=True)
    (cfg / "ioc.yaml").write_text("ioc_name: x\ndescription: d\nentities: []\n")

    result, code = rc.run_reconvert("BL01C", cfg.parents[2], validate=False)

    assert code == 0
    assert len(result.warnings) == 3
    assert {w["ioc_name"] for w in result.warnings} == {IOC.lower()}
    summary = rc._render_human(result)
    assert "Warnings:      3" in summary
    assert "port CAM1.ROT is still referenced by" in summary
