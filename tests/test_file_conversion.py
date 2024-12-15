from pathlib import Path

from builder2ibek.convert import convert_file

conversion_samples = [
    "tests/samples/BL45P-MO-IOC-01.xml",
    "tests/samples/BL99P-EA-IOC-05.xml",
    "tests/samples/SR03-VA-IOC-01.xml",
]


def test_convert(samples: Path):
    samples = samples.glob("*.xml")
    for sample_xml in samples:
        sample_yaml = Path(str(sample_xml.with_suffix(".yaml")).lower())
        out_yaml = Path("/tmp") / sample_yaml.name

        convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

        assert out_yaml.read_text() == sample_yaml.read_text()
