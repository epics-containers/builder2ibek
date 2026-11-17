"""A module with no converter keeps its own name, and never renames another's."""

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from builder2ibek.moduleinfos import module_infos

XML = """\
<components arch="linux-x86_64">
  <noConverterModule.someDevice P="X" name="dev"/>
  <generic.generic_BPM_vert P="BL08I-AL-SLITS-01" KX="1"/>
</components>
"""


def _types(xml: str) -> list[str]:
    builder = Builder()
    builder.load_string(xml)
    return [str(e["type"]) for e in dispatch(builder, "test.xml").entities]


def test_unconverted_module_does_not_rename_generic():
    types = _types(XML)

    assert "noConverterModule.someDevice" in types
    assert "generic.generic_BPM_vert" in types
    assert module_infos["generic"].yaml_component == "generic"


def test_later_ioc_in_the_same_process_keeps_generic():
    """beamline2yaml and reconvert dispatch many XMLs in one process."""
    _types(XML)
    second = '<components arch="linux-x86_64">' + XML.splitlines()[2] + "</components>"

    assert "generic.generic_BPM_vert" in _types(second)
