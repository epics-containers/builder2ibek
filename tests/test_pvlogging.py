"""
The pvlogging BlacklistPv handler writes <ioc>_blacklist.txt as a side file of
the conversion, accumulating every BlacklistPv entity of the IOC into it.
"""

import re
from pathlib import Path

from builder2ibek.convert import convert_file

SCHEMA = "/epics/ibek-defs/ioc.schema.json"
SAMPLE = "BL21I-MO-IOC-01"


def _convert(xml: Path, out_dir: Path) -> Path:
    """Convert xml into out_dir/ioc.yaml and return the blacklist it wrote."""
    convert_file(xml, out_dir / "ioc.yaml", SCHEMA)
    return out_dir / f"{xml.stem.lower()}_blacklist.txt"


def _pvs(blacklist: Path) -> list[str]:
    lines = blacklist.read_text().splitlines()
    return [line for line in lines if line and not line.startswith("#")]


def test_blacklist_written_next_to_yaml(samples: Path, tmp_path: Path, monkeypatch):
    """The blacklist goes beside the converted YAML, never into the cwd."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    blacklist = _convert(samples / f"{SAMPLE}.xml", tmp_path / "out")

    expected = samples / f"{SAMPLE.lower()}_blacklist.txt"
    assert blacklist.read_text() == expected.read_text()
    assert list(cwd.iterdir()) == []


def test_blacklist_is_per_conversion(samples: Path, tmp_path: Path):
    """
    `builder2ibek reconvert` converts a whole beamline in one process. Each
    IOC must get a blacklist of its own PVs only, and converting the same IOC
    again must not carry anything over from the previous run.
    """
    xml1 = samples / f"{SAMPLE}.xml"
    xml2 = tmp_path / "BL21I-MO-IOC-02.xml"
    xml2.write_text(re.sub(r'name="black', 'name="white', xml1.read_text()))

    first = _convert(xml1, tmp_path / "ioc01")
    assert _pvs(first) == ["black1", "black2", "blackagain"]

    # same IOC, same output folder, straight after itself in the same process
    again = _convert(xml1, tmp_path / "ioc01")
    assert _pvs(again) == ["black1", "black2", "blackagain"]

    second = _convert(xml2, tmp_path / "ioc02")
    assert _pvs(second) == ["white1", "white2", "whiteagain"]
