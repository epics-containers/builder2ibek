"""
The ioc.yaml schema header: the instance's own schema in a services repo, as
its ibek-ioc-schema pre-commit hook writes it, else the one given.
"""

from pathlib import Path

import pytest
from ibek.pattern_cmds.schema import SCHEMA_HEADER, rewrite_ioc_yaml_header

from builder2ibek import convert
from builder2ibek.vendor_patterns import PatternReport

XML = """\
<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <EPICS_BASE.EpicsEnvSet key="EPICS_TZ" value="GMT0BST"/>
</components>
"""
IMAGE_SCHEMA = "/epics/ibek-defs/ioc.schema.json"


@pytest.fixture
def xml(tmp_path: Path, monkeypatch) -> Path:
    # the header does not depend on the runtime patterns
    monkeypatch.setattr(convert, "add_patterns", lambda *args: PatternReport())
    path = tmp_path / "BL99I-XX-IOC-01.xml"
    path.write_text(XML)
    return path


def test_instance_ioc_yaml_names_the_instance_schema(tmp_path: Path, xml: Path):
    instance = tmp_path / "services" / "bl99i-xx-ioc-01"
    (instance / "config").mkdir(parents=True)
    (instance / "values.yaml").write_text("ioc-instance:\n  image: REPLACE\n")
    ioc_yaml = instance / "config" / "ioc.yaml"

    convert.convert_file(xml, ioc_yaml, IMAGE_SCHEMA)

    written = ioc_yaml.read_text()
    assert written.splitlines()[0] == SCHEMA_HEADER
    # the pre-commit hook's rewrite leaves it as it is
    rewrite_ioc_yaml_header(ioc_yaml)
    assert ioc_yaml.read_text() == written


def test_other_ioc_yaml_names_the_given_schema(tmp_path: Path, xml: Path):
    ioc_yaml = tmp_path / "ioc.yaml"

    convert.convert_file(xml, ioc_yaml, IMAGE_SCHEMA)

    first = ioc_yaml.read_text().splitlines()[0]
    assert first == f"# yaml-language-server: $schema={IMAGE_SCHEMA}"
