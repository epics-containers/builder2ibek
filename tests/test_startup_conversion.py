"""
Conversion of the startup-script elements of a builder XML: EPICS_BASE dbpf,
EpicsEnvSet and StartupCommand, and the utility module's wait commands.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from builder2ibek.builder import Builder
from builder2ibek.convert import convert_file, dispatch
from tests.conftest import requires_support


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
    assert zebra["PREC"] == "" and zebra["M1MULT"] == "0.25"
    (cori,) = of_type(entities, "bronkhorstFlowBus.coriFlow")
    assert cori["NODE"] == ""


def test_empty_attribute_no_converter_handles():
    """A str parameter no converter touches is "" too, overriding a model
    default the builder never used; an empty float, which the builder could not
    have converted, takes the model default."""
    entities = convert(
        '<mks937b.mks937bRelays GAUGE="IMG01" relay_desc="MPS I/L 1"'
        ' relay_off_desc="" relay_number="2" relay_off_level=""/>'
    )
    (relays,) = of_type(entities, "mks937b.mks937bRelays")
    assert relays["relay_off_desc"] == ""
    assert "relay_off_level" not in relays


@pytest.mark.parametrize(
    "spec,value",
    [
        ({"type": "str", "default": "x"}, ""),
        ({"type": "bool", "default": True}, False),
        ({"type": "int", "default": 1}, None),
        ({"type": "float"}, None),
        ({"type": "object"}, None),
        ({"type": "enum", "values": {"A": None, "B": None}}, None),
        ({"type": "enum", "values": {"": None, "B": None}}, ""),
    ],
)
def test_empty_attribute_by_type(monkeypatch, spec: dict, value: Any):
    """As the builder read an empty attribute: str "", bool False; it could not
    convert an int or float, so those take the model default (None)"""
    from builder2ibek import support_defaults

    monkeypatch.setitem(support_defaults._param_specs, "m.e", {"p": spec})
    assert support_defaults.empty_attribute("m.e", "p") == value
    assert support_defaults.empty_attribute("m.e", "unknown") is None
    assert support_defaults.empty_attribute("m.none", "p") is None


@pytest.mark.parametrize(
    "attribute,post_init",
    [
        ("", False),
        (' post_init=""', False),
        (' post_init="FALSE"', False),
        (' post_init="T"', True),
        (' post_init="0"', True),
        (' post_init="yes"', True),
    ],
)
def test_post_init_is_read_as_the_builder_read_it(attribute: str, post_init: bool):
    """Only an empty value or "false", in any case, is False."""
    entities = convert(f'<EPICS_BASE.StartupCommand command="echo x"{attribute}/>')
    (command,) = [e for e in entities if e.get("command") == "echo x"]
    expected = "epics.PostStartupCommand" if post_init else "epics.StartupCommand"
    assert command["type"] == expected


def test_empty_at_end_keeps_xml_order():
    entities = convert(
        '<EPICS_BASE.StartupCommand at_end="" command="echo first"/>\n'
        '<asyn.AsynIP name="gauge" port="127.0.0.1:7005"/>'
    )
    names = [e.get("command") or e.get("name") for e in entities]
    assert names.index("echo first") < names.index("gauge")


def test_pre_init_command_needing_records_warns():
    builder = Builder()
    builder.load_string(
        '<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n'
        '<EPICS_BASE.StartupCommand command="dbpf X:Y 1"/>\n'
        '<EPICS_BASE.StartupCommand command="dbLoadRecords x.db"/>\n'
        '<EPICS_BASE.StartupCommand command="dbpr X:Y" post_init="True"/>\n'
        "</components>"
    )
    ioc = dispatch(builder, Path("BL01C-VA-IOC-01.xml"))
    assert len(ioc.extra_warnings) == 1
    assert "'dbpf X:Y 1' runs before dbLoadRecords" in ioc.extra_warnings[0]


def test_startup_commands_run_where_the_builder_ran_them():
    """
    The builder ran an at_end StartupCommand (the default) after every
    device's commands: pre-init ones after the asyn port they trace is made,
    post-init ones straight after iocInit. at_end="False" keeps XML order.
    """
    entities = convert(
        '<EPICS_BASE.StartupCommand command="asynSetTraceIOMask(&quot;gauge&quot;'
        ', -1, 0x2)" name="IO"/>\n'
        '<EPICS_BASE.StartupCommand at_end="True" command="asynSetTraceMask('
        '&quot;gauge&quot;, -1, 0x9)" name="Trace"/>\n'
        '<EPICS_BASE.StartupCommand at_end="False" command="echo in order"/>\n'
        '<asyn.AsynIP name="gauge" port="127.0.0.1:7005"/>\n'
        '<EPICS_BASE.dbpf pv="BL01C-VA-GAUGE-15:P.EGU" value="mbar"/>\n'
        '<EPICS_BASE.StartupCommand command="echo after iocInit" post_init="True"/>'
        '\n<EPICS_BASE.StartupCommand at_end="False" command="echo post in order"'
        ' post_init="True"/>'
    )
    order = [
        e.get("command") or e.get("name") or e.get("pv")
        for e in entities
        if e["type"].startswith(("epics.", "asyn."))
    ]
    assert order == [
        "echo after iocInit",
        "EPICS_TZ",
        "STREAM_PROTOCOL_PATH",
        "echo in order",
        "gauge",
        "BL01C-VA-GAUGE-15:P.EGU",
        "echo post in order",
        'asynSetTraceIOMask("gauge", -1, 0x2)',
        'asynSetTraceMask("gauge", -1, 0x9)',
    ]
    by_command = {e["command"]: e["type"] for e in entities if "command" in e}
    assert by_command["echo after iocInit"] == "epics.PostStartupCommand"
    assert by_command["echo post in order"] == "epics.PostStartupCommand"
    assert by_command["echo in order"] == "epics.StartupCommand"
    assert all("at_end" not in e and "post_init" not in e for e in entities)


def test_wait_commands_are_dropped():
    entities = convert(
        '<utility.directoryWait directory="/dls_sw/i23/epics/autosave/BL23I-VA-IOC-02"'
        ' name="DIRW" sleepTime="5"/>\n'
        '<utility.pingWait delay="3" ip="127.0.0.1"/>'
    )
    assert not [e for e in entities if e["type"].startswith("utility.")]


@requires_support
def test_st_cmd_has_the_builder_order_and_values(tmp_path: Path, ibek_defs):
    """generate2 renders the converted entities: an empty dbpf and epicsEnvSet
    value, and at_end commands before and after the devices' commands."""
    xml = tmp_path / "BL01C-VA-IOC-01.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n'
        '<EPICS_BASE.EpicsEnvSet key="EMPTY" value=""/>\n'
        '<EPICS_BASE.StartupCommand command="asynSetTraceMask(gauge, -1, 0x9)"/>\n'
        '<EPICS_BASE.StartupCommand command="echo post" post_init="True"/>\n'
        '<asyn.AsynIP name="gauge" port="127.0.0.1:7005"/>\n'
        '<EPICS_BASE.dbpf pv="BL01C-VA-SPACE-13:P.EGU" value=""/>\n'
        "</components>"
    )
    config = tmp_path / "config"
    convert_file(xml, config / "ioc.yaml", "/epics/ibek-defs/ioc.schema.json")
    result = subprocess.run(
        [
            "ibek",
            "runtime",
            "generate2",
            str(config),
            "--output",
            str(tmp_path),
            "--no-pvi",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = (tmp_path / "st.cmd").read_text().splitlines()
    assert 'epicsEnvSet EMPTY ""' in lines
    port = next(i for i, x in enumerate(lines) if x.startswith("drvAsynIPPort"))
    assert lines.index("asynSetTraceMask(gauge, -1, 0x9)") > port
    assert lines.index("iocInit") < lines.index("echo post")
    assert lines.index("echo post") < lines.index('dbpf "BL01C-VA-SPACE-13:P.EGU" ""')
