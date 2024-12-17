from pathlib import Path

from builder2ibek.convert import convert_file

conversion_samples = [
    "tests/samples/BL45P-MO-IOC-01.xml",
    "tests/samples/BL99P-EA-IOC-05.xml",
    "tests/samples/SR03-VA-IOC-01.xml",
]


def test_convert(samples: Path):
    all_samples = samples.glob("*.xml")
    for sample_xml in all_samples:
        sample_yaml = Path(str(sample_xml.with_suffix(".yaml")).lower())
        out_yaml = Path("/tmp") / sample_yaml.name

        convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

        assert out_yaml.read_text() == sample_yaml.read_text()


def test_debug(samples: Path):
    """
    A single test to debug the conversion process
    """
    in_xml = samples / "BL99P-EA-IOC-05.xml"
    out_yml = samples / "BL99P-EA-IOC-05.yaml"
    convert_file(in_xml, out_yml, "/epics/ibek-defs/ioc.schema.json")
