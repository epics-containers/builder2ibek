"""Legacy EtherCAT record suffixes and their fastcs-catio equivalents.

The DLS `ethercat` support module names a record `$(DEVICE):<suffix>`, where
`<suffix>` comes from `db/<terminal>.template` and `DEVICE` is set by the
`auto_<terminal>` entity in the builder XML. fastcs-catio instead names its
attributes from `terminal_types.yaml`, so migrating a consumer's PV reference
means translating the suffix as well as the prefix.

The tables are keyed on the **builder entity type** (`auto_EL3104`), not the
terminal type, because `auto_EL3104` and `auto_EL3104adc` produce byte-identical
suffix sets from different templates -- a consumer's PV string alone cannot
distinguish them.

Suffix inventories were taken from
`/dls_sw/prod/R3.14.12.7/support/ethercat/7-5-3/db/*.template` and proved
exhaustive (every `record(...)` name starts with `$(DEVICE):` and no suffix
contains a further macro). They are byte-identical across ethercat 7-4-3
through 7-5-3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `{n}` in a suffix or fastcs name stands for a 1-based channel number.
_CHANNEL = "{n}"


@dataclass(frozen=True)
class Leaf:
    """One translatable record suffix.

    :param suffix: legacy suffix template, e.g. ``"INPUT{n}:VALUE"``.
    :param fastcs_name: the matching `fastcs_name` from `terminal_types.yaml`,
        e.g. ``"ai_standard_channel_{n}_value"``. fastcs-catio PascalCases this
        to form the PV leaf.
    :param writable: True when the fastcs attribute is `AttrRW`, so FastCS
        creates both a write PV and a `_RBV` readback. Readers of such a signal
        must be pointed at the `_RBV`.
    """

    suffix: str
    fastcs_name: str
    writable: bool = False


# Suffixes a terminal really produces but which fastcs-catio has no equivalent
# for. Referencing one is a migration error, not a silent pass-through: the new
# IOC simply will not have that PV.
#
# The EL3104 status bits below exist as PDO entries but are not selected in
# terminal_types.yaml. The EL3356 RMBSTATUS/RMBCONTROL bits are worse -- their
# fastcs counterparts (`rmb_status`, `rmb_control`) are single packed bitfield
# attributes, so there is no per-bit PV to point at.
_EL3104_UNMAPPED = tuple(
    f"INPUT{{n}}:{s}"
    for s in (
        "SUNDERRANGE",
        "SOVERRANGE",
        "SERROR",
        "SSYNCERROR",
        "STXPDOSTATE",
        "STXPDOTOGGLE",
    )
)

_EL3356_UNMAPPED = (
    "RMBSTATUS:SOVERRANGE",
    "RMBSTATUS:ST_DATAINVALID",
    "RMBSTATUS:SERROR",
    "RMBSTATUS:ST_CIP",
    "RMBSTATUS:ST__STEADYSTATE",
    "RMBSTATUS:SSYNCERROR",
    "RMBSTATUS:STXPDOTOGGLE",
    "RMBCONTROL:CTRL_STARTCLB",
    "RMBCONTROL:CTRL__DISABLECALIBRATION",
    "RMBCONTROL:CTRL_INPUTFREEZE",
    "RMBCONTROL:CTRL_SAMPLEMODE",
    "RMBCONTROL:CTRL_TARA",
)

# Every terminal template also declares these two. `AL_STATE` is the EtherCAT
# state machine and `ERROR_FLAG` the slave error latch; fastcs-catio's nearest
# equivalent, `wcstate`, is a working-counter status and is not the same signal.
_COMMON_UNMAPPED = ("AL_STATE", "ERROR_FLAG")


@dataclass(frozen=True)
class TerminalLeaves:
    """The translation table for one builder entity type."""

    entity_type: str
    terminal_type: str
    leaves: tuple[Leaf, ...]
    unmapped: tuple[str, ...] = ()
    channels: int = 4


TERMINALS: dict[str, TerminalLeaves] = {
    t.entity_type: t
    for t in (
        TerminalLeaves(
            entity_type="auto_EL3104",
            terminal_type="EL3104",
            leaves=(
                Leaf("INPUT{n}:VALUE", "ai_standard_channel_{n}_value"),
                Leaf("INPUT{n}:SLIMIT1", "ai_std_ch_{n}_sts_lim_1"),
                Leaf("INPUT{n}:SLIMIT2", "ai_std_ch_{n}_sts_lim_2"),
            ),
            unmapped=_COMMON_UNMAPPED + _EL3104_UNMAPPED,
        ),
        # Same template shape, `ai` records with EGU scaling instead of `longin`.
        TerminalLeaves(
            entity_type="auto_EL3104adc",
            terminal_type="EL3104",
            leaves=(
                Leaf("INPUT{n}:VALUE", "ai_standard_channel_{n}_value"),
                Leaf("INPUT{n}:SLIMIT1", "ai_std_ch_{n}_sts_lim_1"),
                Leaf("INPUT{n}:SLIMIT2", "ai_std_ch_{n}_sts_lim_2"),
            ),
            unmapped=_COMMON_UNMAPPED + _EL3104_UNMAPPED,
        ),
        TerminalLeaves(
            entity_type="auto_EL1014",
            terminal_type="EL1014",
            leaves=(Leaf("CHANNEL{n}:INPUT", "channel_{n}"),),
            unmapped=_COMMON_UNMAPPED,
        ),
        TerminalLeaves(
            entity_type="auto_EL2024_0010",
            terminal_type="EL2024-0010",
            leaves=(Leaf("CHANNEL{n}:OUTPUT", "channel_{n}", writable=True),),
            unmapped=_COMMON_UNMAPPED,
        ),
        TerminalLeaves(
            entity_type="auto_EL3356_0010",
            terminal_type="EL3356-0010",
            leaves=(Leaf("RMB:VALUE", "rmb_value_int32_value"),),
            unmapped=_COMMON_UNMAPPED + _EL3356_UNMAPPED,
            channels=1,
        ),
    )
}

#: Entity types whose terminal has a translation table.
KNOWN_ENTITY_TYPES = frozenset(TERMINALS)


def snake_to_pascal(name: str) -> str:
    """PascalCase a fastcs snake_case name, as `fastcs.util.snake_to_pascal` does.

    Only strings that are wholly lower-case snake_case are transformed; anything
    else is returned unchanged, which is what keeps PV segments such as
    ``10VAI01`` intact.

    >>> snake_to_pascal("ai_standard_channel_1_value")
    'AiStandardChannel1Value'
    >>> snake_to_pascal("channel_2")
    'Channel2'
    >>> snake_to_pascal("10VAI01")
    '10VAI01'

    Only the first character of a part is raised, never one following a digit --
    ``str.title()`` would give ``'Ch1A'`` here and diverge from the PV fastcs
    actually creates:

    >>> snake_to_pascal("ch1a")
    'Ch1a'
    """
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name):
        return name
    return re.sub(r"(?:^|_)([a-z0-9])", lambda m: m.group(1).upper(), name)


def _expand(template: str, channel: int | None) -> str:
    return template.replace(_CHANNEL, str(channel)) if channel else template


def leaf_translations(entity_type: str) -> dict[str, Leaf]:
    """Every legacy suffix of *entity_type*, channel numbers expanded.

    :returns: legacy suffix -> the :class:`Leaf` describing its replacement,
        with `{n}` already substituted in both.

    >>> leaf_translations("auto_EL1014")["CHANNEL3:INPUT"].fastcs_name
    'channel_3'
    """
    terminal = TERMINALS[entity_type]
    out: dict[str, Leaf] = {}
    for leaf in terminal.leaves:
        numbered = _CHANNEL in leaf.suffix
        channels = range(1, terminal.channels + 1) if numbered else [None]
        for channel in channels:
            suffix = _expand(leaf.suffix, channel)
            out[suffix] = Leaf(
                suffix=suffix,
                fastcs_name=_expand(leaf.fastcs_name, channel),
                writable=leaf.writable,
            )
    return out


def unmapped_suffixes(entity_type: str) -> set[str]:
    """Legacy suffixes of *entity_type* that fastcs-catio has no PV for.

    >>> "AL_STATE" in unmapped_suffixes("auto_EL1014")
    True
    """
    terminal = TERMINALS[entity_type]
    out: set[str] = set()
    for suffix in terminal.unmapped:
        channels = range(1, terminal.channels + 1) if _CHANNEL in suffix else [None]
        out.update(_expand(suffix, channel) for channel in channels)
    return out


def pv_leaf(leaf: Leaf, *, reading: bool) -> str:
    """The PV leaf a consumer should point at.

    FastCS gives a read/write attribute two PVs: the setpoint under its own
    name, and a readback suffixed ``_RBV``. A link that *reads* the signal must
    use the readback.

    >>> pv_leaf(Leaf("CHANNEL1:OUTPUT", "channel_1", writable=True), reading=True)
    'Channel1_RBV'
    >>> pv_leaf(Leaf("CHANNEL1:OUTPUT", "channel_1", writable=True), reading=False)
    'Channel1'
    >>> pv_leaf(Leaf("INPUT1:VALUE", "ai_standard_channel_1_value"), reading=True)
    'AiStandardChannel1Value'
    """
    name = snake_to_pascal(leaf.fastcs_name)
    return f"{name}_RBV" if leaf.writable and reading else name
