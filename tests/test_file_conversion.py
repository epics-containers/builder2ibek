"""
Tests to validate that the conversion of the xml files to yaml files is correct.
"""

from pathlib import Path

from builder2ibek.convert import convert_file
from builder2ibek.converters.epics_base import InterruptVector


def test_convert(samples: Path):
    all_samples = samples.glob("*.xml")
    for sample_xml in all_samples:
        sample_yaml = Path(str(sample_xml.with_suffix(".yaml")).lower())
        out_yaml = Path("/tmp") / sample_yaml.name

        convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

        assert out_yaml.read_text() == sample_yaml.read_text()
        # reset the interrupt vector counter
        InterruptVector.reset()


def test_debug(samples: Path):
    """
    A single test to debug the conversion process (a redundant test, just useful
    for launching the debugger against the convert_file function)
    """
    in_xml = samples / "BL99P-EA-IOC-05.xml"
    out_yml = samples / "BL99P-EA-IOC-05.yaml"
    convert_file(in_xml, out_yml, "/epics/ibek-defs/ioc.schema.json")
