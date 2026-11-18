"""
slsDetector converts to the ibek-support model when it uses the numModules API
of slsDetectorPackage, and is left out when it uses the older useReceiver API.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <slsDetector.slsDetector ADDR="0" P="BL01C-EA-DET-01" PORT="MYTHEN3.DET"
    R=":DET:" TIMEOUT="10" cacheConfigFile="false" configFile="/m3.config"
    detectorIndex="0" name="MYTHEN3.DET" numModules="28" iocName="BL01C-EA-IOC-01"/>
  <slsDetector.slsDetector ADDR="0" P="BL01C-EA-MYTHN-01" PORT="MYTHEN3.CAM"
    R=":CAM:" TIMEOUT="10" configFileName="/m30.config" detectorId="1"
    name="MYTHEN3.CAM"/>
  <slsDetector.slsDetector ADDR="0" P="BL01C-EA-DET-02" PORT="MYTHEN.DET"
    R=":DET:" TIMEOUT="10" configFile="/m.config" detectorIndex="0"
    name="MYTHEN.DET" useReceiver="0"/>
  <ADCore.NDROI ADDR="0" NDARRAY_PORT="MYTHEN.DET" P="BL01C-EA-DET-02"
    PORT="MYTHEN.ROI" R=":ROI:" TIMEOUT="1"/>
</components>
"""


def test_slsdetector(tmp_path: Path):
    xml = tmp_path / "BL01C-EA-IOC-01.xml"
    xml.write_text(XML)
    yaml = tmp_path / "ioc.yaml"
    result = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")
    entities = [
        e
        for e in YAML(typ="safe").load(yaml.read_text())["entities"]
        if e["type"].startswith("slsDetector.")
    ]

    common = {"type": "slsDetector.slsDetectorConfigure", "TIMEOUT": 10}
    common |= {"BUFFERS": 50, "MEMORY": 0}
    assert entities == [
        common
        | {
            "P": "BL01C-EA-DET-01",
            "PORT": "MYTHEN3.DET",
            "R": ":DET:",
            "configFile": "/m3.config",
            "detectorIndex": 0,
            "numModules": 28,
        },
        common
        | {
            "P": "BL01C-EA-MYTHN-01",
            "PORT": "MYTHEN3.CAM",
            "R": ":CAM:",
            "configFile": "/m30.config",
            "detectorIndex": 1,
            "numModules": 1,
        },
    ]
    (warning,) = result.warnings
    assert "won't convert 1 slsDetector.slsDetector" in warning
    assert "useReceiver" in warning
    assert "port MYTHEN.DET is still referenced by: ADCore.NDROI" in warning
