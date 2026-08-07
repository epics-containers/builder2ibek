"""
Tests for the ethercat converter and the catio plumbing in convert.py.

Deliberately duck-typed: no import of builder2ibek.catio.substitute, so these
tests do not depend on modules that are still being written.
"""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from builder2ibek.builder import Builder
from builder2ibek.convert import (
    convert_file,
    convert_to_ioc,
    dispatch,
    write_ioc_yaml,
)
from builder2ibek.converters import ethercat
from builder2ibek.converters.epics_base import InterruptVector
from builder2ibek.converters.ethercat import CatioContext, finalize
from builder2ibek.types import Generic_IOC

TODO_COMMAND = (
    "# TODO: ethercat support requires major rewrite for "
    "epics-containers — switch to fastcs-catio"
)

ETHERCAT_XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <ethercat.EthercatMaster name="MASTER" socket="/tmp/ethercat.sock"/>
  <ethercat.EthercatSlave name="SLAVE1" position="1" type_name="EL3104"
    type_rev="0x00120000" oversample="0"/>
  <ethercat.auto_EL3104 PORT="SLAVE1" DEVICE="BL21I-VA-ERIO-01:MOD1"/>
  <calculation.Calc name="CALC1" INPA="BL21I-VA-ERIO-01:MOD1:AI1 CP"
    INPB="BL21I-VA-ERIO-01:MOD1:AI2 CP" CALC="A+B"/>
</components>
"""


class StubSubstituter:
    """Minimal object satisfying the Substituter.rewrite_entity contract."""

    def __init__(self, subs: dict[str, str]):
        self.subs = subs
        self.calls: list[tuple[str, str | None]] = []
        self.dropped: list[tuple[str, int, int]] = []

    def report_dropped(self, raw_entities, kept_entities, *, log, ioc) -> list[str]:
        self.dropped.append((ioc, len(list(raw_entities)), len(list(kept_entities))))
        return []

    def rewrite_entity(self, entity: dict, *, log, ioc: str) -> bool:
        self.calls.append((ioc, entity.get("type")))
        changed = False
        for key, value in list(entity.items()):
            if not isinstance(value, str):
                continue
            new = " ".join(self.subs.get(tok, tok) for tok in value.split(" "))
            if new != value:
                entity[key] = new
                changed = True
        return changed


class StubLog:
    """Stand-in for DiagnosticLog -- the stub substituter never writes to it."""

    def __init__(self) -> None:
        self.entries: list[tuple] = []

    def add(self, code, message, **kwargs):
        self.entries.append((code, message, kwargs))


SUBS = {
    "BL21I-VA-ERIO-01:MOD1:AI1": "BL21I-VA-E1RIO-01:AI01:Channel1",
    "BL21I-VA-ERIO-01:MOD1:AI2": "BL21I-VA-E1RIO-01:AI01:Channel2",
}


def convert_xml(xml_str: str, catio=None) -> Generic_IOC:
    builder = Builder()
    builder.load_string(xml_str)
    return dispatch(builder, Path("inline.xml"), catio=catio)


def entity_types(ioc: Generic_IOC) -> list[str]:
    return [e["type"] for e in ioc.entities]


def calc_entity(ioc: Generic_IOC) -> dict:
    (calc,) = [e for e in ioc.entities if e["type"] == "calculation.Calc"]
    return calc


# --- ethercat entity conversion (unchanged behaviour) ----------------------


def test_ethercat_master_becomes_post_startup_todo():
    ioc = convert_xml(ETHERCAT_XML)
    (placeholder,) = [
        e for e in ioc.entities if e["type"] == "epics.PostStartupCommand"
    ]
    assert placeholder["command"] == TODO_COMMAND
    # the master's own args are gone
    assert "socket" not in placeholder
    assert "name" not in placeholder


def test_other_ethercat_entities_are_dropped():
    ioc = convert_xml(ETHERCAT_XML)
    assert not [t for t in entity_types(ioc) if t.startswith("ethercat.")]


def test_dead_global_is_gone():
    """_dummy_inserted leaked across IOCs in a multi-IOC process."""
    assert not hasattr(ethercat, "_dummy_inserted")


def test_two_masters_both_become_placeholders():
    """No per-process state: a second master converts exactly like the first."""
    two = ETHERCAT_XML.replace(
        '<ethercat.EthercatMaster name="MASTER" socket="/tmp/ethercat.sock"/>',
        '<ethercat.EthercatMaster name="MASTER" socket="/tmp/a.sock"/>\n'
        '  <ethercat.EthercatMaster name="MASTER2" socket="/tmp/b.sock"/>',
    )
    ioc = convert_xml(two)
    placeholders = [e for e in ioc.entities if e["type"] == "epics.PostStartupCommand"]
    assert len(placeholders) == 2
    assert all(p["command"] == TODO_COMMAND for p in placeholders)


# --- finalize: no catio context -------------------------------------------


def test_no_catio_context_converts_as_before():
    plain = convert_xml(ETHERCAT_XML)
    assert calc_entity(plain)["INPA"] == "BL21I-VA-ERIO-01:MOD1:AI1 CP"
    assert "catio" not in plain.model_dump()


def test_finalize_is_a_noop_without_context():
    ioc = Generic_IOC(
        ioc_name="x",
        description="",
        entities=[{"type": "a.B", "v": "hello"}],
        source_file=Path("x.xml"),
    )
    finalize(ioc)
    assert ioc.entities == [{"type": "a.B", "v": "hello"}]


# --- finalize: with a catio context ----------------------------------------


def test_catio_context_rewrites_entity_values():
    sub = StubSubstituter(SUBS)
    ctx = CatioContext(substituter=sub, log=StubLog(), ioc_name="BL21I-VA-IOC-02")
    ioc = convert_xml(ETHERCAT_XML, catio=ctx)

    calc = calc_entity(ioc)
    assert calc["INPA"] == "BL21I-VA-E1RIO-01:AI01:Channel1 CP"
    assert calc["INPB"] == "BL21I-VA-E1RIO-01:AI01:Channel2 CP"


def test_catio_context_sees_every_entity_and_the_ioc_name():
    sub = StubSubstituter(SUBS)
    ctx = CatioContext(substituter=sub, log=StubLog(), ioc_name="BL21I-VA-IOC-02")
    ioc = convert_xml(ETHERCAT_XML, catio=ctx)

    assert {ioc_name for ioc_name, _ in sub.calls} == {"BL21I-VA-IOC-02"}
    assert len(sub.calls) == len(ioc.entities)
    # including the entities dispatch() adds by default
    assert "devIocStats.iocAdminSoft" in {t for _, t in sub.calls}


def test_catio_attribute_is_removed_from_the_model():
    sub = StubSubstituter(SUBS)
    ctx = CatioContext(substituter=sub, log=StubLog(), ioc_name="BL21I-VA-IOC-02")
    ioc = convert_xml(ETHERCAT_XML, catio=ctx)

    assert getattr(ioc, "catio", None) is None
    assert "catio" not in ioc.model_dump()


def test_catio_attribute_is_removed_even_if_rewriting_raises():
    class Boom:
        def rewrite_entity(self, entity, *, log, ioc):
            raise RuntimeError("boom")

    ioc = Generic_IOC(
        ioc_name="x",
        description="",
        entities=[{"type": "a.B"}],
        source_file=Path("x.xml"),
    )
    ioc.catio = CatioContext(substituter=Boom(), log=StubLog(), ioc_name="X")
    with pytest.raises(RuntimeError):
        finalize(ioc)
    assert "catio" not in ioc.model_dump()


def test_catio_key_absent_from_written_yaml(tmp_path: Path):
    sub = StubSubstituter(SUBS)
    ctx = CatioContext(substituter=sub, log=StubLog(), ioc_name="BL21I-VA-IOC-02")
    ioc = convert_xml(ETHERCAT_XML, catio=ctx)

    out = tmp_path / "ioc.yaml"
    write_ioc_yaml(ioc, out, "/epics/ibek-defs/ioc.schema.json")

    text = out.read_text()
    # "catio" as a top-level YAML key (the TODO placeholder legitimately
    # mentions fastcs-catio in a value)
    assert "\ncatio" not in text
    assert "BL21I-VA-E1RIO-01:AI01:Channel1 CP" in text

    loaded = YAML().load(text)
    assert set(loaded) == {"ioc_name", "description", "entities"}


# --- convert_to_ioc / write_ioc_yaml split ---------------------------------


def test_convert_to_ioc_matches_convert_file(tmp_path: Path, samples: Path):
    """The refactor must not change convert_file's output at all."""
    xml = samples / "BL99P-EA-IOC-05.xml"

    try:
        via_convert_file = tmp_path / "a.yaml"
        convert_file(xml, via_convert_file, "/epics/ibek-defs/ioc.schema.json")
        InterruptVector.reset()

        via_split = tmp_path / "b.yaml"
        write_ioc_yaml(
            convert_to_ioc(xml), via_split, "/epics/ibek-defs/ioc.schema.json"
        )
    finally:
        # this module-level counter leaks between conversions
        InterruptVector.reset()

    assert via_split.read_text() == via_convert_file.read_text()


def test_convert_to_ioc_passes_catio_through(tmp_path: Path):
    xml = tmp_path / "inline.xml"
    xml.write_text(ETHERCAT_XML)

    sub = StubSubstituter(SUBS)
    ctx = CatioContext(substituter=sub, log=StubLog(), ioc_name="BL21I-VA-IOC-02")
    ioc = convert_to_ioc(xml, catio=ctx)

    assert calc_entity(ioc)["INPA"] == "BL21I-VA-E1RIO-01:AI01:Channel1 CP"
    assert sub.calls
