"""
The builder objects adUtil.gdaPlugins and gdaPlugins.gdaPlugins become one
detectorPlugins.gdaPlugins entity, from the ibek-runtime-support pattern, with
the XML's attributes as its parameters.
"""

from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import ConvertResult, convert_file
from tests.pattern_pins import SUPPORT_PATTERN_TAG

PATTERN = f"ibek-runtime-support:detectorPlugins@{SUPPORT_PATTERN_TAG}"

CAMERA = (
    '<ADAndor3.andor3 P="BL01C-EA-DET-01" R=":CAM:" PORT="DET.cam" '
    'CAMERA="0" name="DET.cam"/>'
)


def _convert(tmp_path: Path, gda: str) -> tuple[list[dict], ConvertResult]:
    xml = tmp_path / "BL01C-EA-IOC-01.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n'
        f"{CAMERA}\n{gda}\n</components>\n"
    )
    yaml = tmp_path / "ioc.yaml"
    result = convert_file(xml, yaml, "/epics/ibek-defs/ioc.schema.json")
    entities = YAML(typ="safe").load(yaml.read_text())["entities"]
    return [e for e in entities if "gdaPlugins" in e["type"]], result


def test_adutil_gdaplugins(tmp_path: Path):
    entities, result = _convert(
        tmp_path,
        '<adUtil.gdaPlugins ARRTYPE="Int16" ARRFTVL="SHORT" CAM="DET.cam" '
        'P="BL01C-EA-DET-01" PORTPREFIX="DET" threads="4" name="gda"/>',
    )
    # the pattern's defaults are adUtil's, so none is added
    assert entities == [
        {
            "type": "detectorPlugins.gdaPlugins",
            "ARRFTVL": "SHORT",
            "ARRTYPE": "Int16",
            "CAM": "DET.cam",
            "P": "BL01C-EA-DET-01",
            "PORTPREFIX": "DET",
            "threads": 4,
        }
    ]
    assert not [w for w in result.warnings if "detectorPlugins" in w]
    assert f"would add runtime pattern {PATTERN}" in result.notes


def test_gdaplugins_module_keeps_its_template_defaults(tmp_path: Path):
    entities, _ = _convert(
        tmp_path,
        '<gdaPlugins.gdaPlugins CAM="DET.cam" P="BL01C-EA-DET-01" '
        'PORTPREFIX="DET" XSIZE="2048" name="gda"/>',
    )
    # gdaPlugins 1-2 defaults NCHANS and YSIZE to 20000 and 768, not 1024
    assert entities == [
        {
            "type": "detectorPlugins.gdaPlugins",
            "CAM": "DET.cam",
            "P": "BL01C-EA-DET-01",
            "PORTPREFIX": "DET",
            "XSIZE": 2048,
            "NCHANS": 20000,
            "YSIZE": 768,
        }
    ]


def test_gdaplugins_module_keeps_given_sizes(tmp_path: Path):
    entities, _ = _convert(
        tmp_path,
        '<gdaPlugins.gdaPlugins CAM="DET.cam" P="BL01C-EA-DET-01" '
        'PORTPREFIX="DET" NCHANS="100" YSIZE="512" name="gda"/>',
    )
    assert entities[0]["NCHANS"] == 100
    assert entities[0]["YSIZE"] == 512


def test_unsupported_arrtype_is_an_unresolved_module(tmp_path: Path):
    """An ARRTYPE the pattern's enum lacks keeps the entity, and the module is
    reported unresolved, saying why the pattern rejects it."""
    entities, result = _convert(
        tmp_path,
        '<adUtil.gdaPlugins ARRTYPE="UInt16" CAM="DET.cam" P="BL01C-EA-DET-01" '
        'PORTPREFIX="DET" name="gda"/>',
    )
    assert [e["ARRTYPE"] for e in entities] == ["UInt16"]
    unresolved = [
        w for w in result.warnings if "unresolved module detectorPlugins" in w
    ]
    assert len(unresolved) == 1
    assert f"{PATTERN} rejects" in unresolved[0]
    assert "ARRTYPE" in unresolved[0]
    assert not [n for n in result.notes if "would add runtime pattern" in n]
