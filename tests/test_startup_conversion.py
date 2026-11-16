"""
Conversion of the startup-script elements of a builder XML: EPICS_BASE dbpf,
EpicsEnvSet and StartupCommand, and the utility module's wait commands.
"""

from pathlib import Path
from typing import Any

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch


def convert(body: str) -> list[dict[str, Any]]:
    """The entities converted from the XML elements in ``body``."""
    builder = Builder()
    builder.load_string(
        f'<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n{body}\n'
        "</components>"
    )
    ioc = dispatch(builder, Path("BL01C-VA-IOC-01.xml"))
    return [dict(e) for e in ioc.entities]


def of_type(entities: list[dict[str, Any]], entity_type: str) -> list[dict]:
    return [e for e in entities if e["type"] == entity_type]


def test_dbpf_empty_value_stays_empty():
    entities = convert(
        '<EPICS_BASE.dbpf pv="BL01C-VA-SPACE-13:P.EGU" value=""/>\n'
        '<EPICS_BASE.dbpf pv="BL01C-VA-SPACE-13:P.DESC" value="Space 13"/>'
    )
    assert of_type(entities, "epics.dbpf") == [
        {"type": "epics.dbpf", "pv": "BL01C-VA-SPACE-13:P.EGU", "value": ""},
        {"type": "epics.dbpf", "pv": "BL01C-VA-SPACE-13:P.DESC", "value": "Space 13"},
    ]


def test_epics_env_set_empty_value_is_quoted():
    """ibek writes the value unquoted and iocsh rejects a missing one, so an
    empty value is written as "", which sets the variable empty."""
    entities = convert('<EPICS_BASE.EpicsEnvSet key="EMPTY" value=""/>')
    assert of_type(entities, "epics.EpicsEnvSet")[-1] == {
        "type": "epics.EpicsEnvSet",
        "name": "EMPTY",
        "value": '""',
    }


def test_empty_str_param_stays_empty():
    """The builder passed an empty attribute on as "", so a required str
    parameter gets "" rather than nothing, which would fail validation."""
    entities = convert(
        '<positioner.multipositioner name="MP" P="BL01C-MO-POS-01"/>\n'
        '<positioner.positioner DEADBAND="" MP="MP" name="P1" VALUE="1"/>\n'
        '<lakeshore336.lakeshore336 P="BL01C-EA-TCTRL-01" PORT="ls" ADDR="0"'
        ' SCAN="" TEMPSCAN="5" name="LS"/>'
    )
    (positioner,) = of_type(entities, "positioner.positioner")
    assert positioner["DEADBAND"] == ""
    (lakeshore,) = of_type(entities, "lakeshore336.lakeshore336")
    assert lakeshore["SCAN"] == "" and lakeshore["TEMPSCAN"] == "5"


def test_empty_optional_str_param_stays_empty():
    """An optional parameter left empty is "" too, as the builder passed it."""
    entities = convert(
        '<zebra.zebra PREC="" M1MULT="0.25" P="BL01C-EA-ZEBRA-01" PORT="z" name="Z"/>'
        '\n<bronkhorstFlowBus.coriFlow NODE="" P="BL01C-EA-FLOW-01" PORT="f"/>'
    )
    (zebra,) = of_type(entities, "zebra.zebra")
    (zebra,) = of_type(entities, "zebra.zebra")
    assert zebra["PREC"] == "" and zebra["M1MULT"] == "0.25"
    (cori,) = of_type(entities, "bronkhorstFlowBus.coriFlow")
    assert cori["NODE"] == ""
