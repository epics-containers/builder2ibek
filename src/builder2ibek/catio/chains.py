"""EtherCAT chain modelling: builder XML in, fastcs-catio PV names out.

A DLS *scanner* IOC declares one EtherCAT master and its bus in builder XML::

    <ethercat.EthercatMaster name="ECATM" socket="/tmp/socket0"/>
    <ethercat.EthercatSlave name="DCS00025070" type_rev="EK1100 rev 0x00120000"/>
    <ethercat.EthercatSlave name="DCS00024908" type_rev="EL3104 rev 0x00120000"/>
    <ethercat.auto_EL3104 DEVICE="BL21I-VA-ERIO-04:MOD1" PORT="DCS00024908"/>

`EthercatSlave` elements are in true bus order; each `auto_*` entity binds to one
of them through ``PORT=`` and declares the PV prefix the legacy IOC gave that
terminal in ``DEVICE=``. This module turns that into a :class:`Chain`, predicts
the prefix fastcs-catio will use for every terminal, and assembles the
:class:`~builder2ibek.catio.substitute.Substituter` that rewrites consumers.

Node indexing follows fastcs-catio, **not** the fixtures
-------------------------------------------------------

:data:`Slave.node` is 1-based: node 0 is reserved for slaves that appear ahead
of the first coupler, exactly as ``fastcs_catio.naming._locate`` numbers them.
That is what makes ``predict_prefixes()[(slave.node, slave.position)]`` a direct
lookup. ``tests/samples/catio/expected_chains.json`` and
``.catio-spec/spec_ground.json`` instead number couplers from 0, so a fixture's
``node`` is this module's ``node`` minus one.

The dual-key substitution map
-----------------------------

Each terminal contributes **two** families of legacy PV name:

1. **declared** -- ``{DEVICE}:{suffix}``. Authoritative: this is literally the
   name the legacy IOC's records were created with.
2. **chain-derived** -- ``{coupler label}:MOD{position}:{suffix}``. A best-effort
   alias for consumers that followed bus position rather than the declaration.

Where the two disagree the **declared name wins and the derived alias is
dropped**. This matters: ``BL21I-DI-ERIO-01`` has a terminal declaring ``MOD10``
at bus position 14 *and* a different terminal at bus position 10. Only the
declared name ever existed as a record, so a consumer writing
``BL21I-DI-ERIO-01:MOD10:CHANNEL1:OUTPUT`` provably meant position 14. Treating
that as an unresolvable ambiguity would fail the whole `BL21I-DI-IOC-01` chain
for no reason; 78 keys are in this position on I21 alone.

Genuine ambiguity -- two *declared* names, or two *derived* names, resolving to
different terminals -- still drops the key into ``unresolved`` under
``ambiguous-legacy-pv``. Because whether anything references it is not known
until substitution has run, the CLI calls :func:`report_unused_ambiguities`
afterwards to downgrade the untouched ones to ``ambiguous-legacy-pv-unused``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from builder2ibek.builder import Builder
from builder2ibek.catio.diagnostics import DiagnosticLog
from builder2ibek.catio.leaves import (
    KNOWN_ENTITY_TYPES,
    TERMINALS,
    leaf_translations,
    pv_leaf,
    unmapped_suffixes,
)
from builder2ibek.catio.substitute import NewPv, Substituter, SubstitutionMap

__all__ = [
    "BOX",
    "BOX_TYPE_RE",
    "COUPLER",
    "COUPLER_TYPE",
    "EXTENSION_TYPE",
    "MAKE_IOCS",
    "SLAVE",
    "Chain",
    "Slave",
    "UnresolvedMap",
    "build_substituter",
    "catio_ioc_name",
    "chain_by_ioc",
    "discover_chains",
    "domain_of",
    "is_scanner",
    "parse_chain",
    "predict_prefixes",
    "report_unused_ambiguities",
]

#: Exact type string that opens a new coupler node. Mirrors
#: ``fastcs_catio.naming.COUPLER_TYPE``.
COUPLER_TYPE = "EK1100"

#: Bus extension; ahead of the first coupler it burns one position to reserve
#: the slot of an EK1200 that TwinCAT does not report. Mirrors
#: ``fastcs_catio.naming.EXTENSION_TYPE``.
EXTENSION_TYPE = "EK1110"

#: A box is a coupler-and-terminals in one housing. Anchored, and deliberately
#: *not* matching ``EK1122`` junctions, which take an ordinary position. Mirrors
#: ``fastcs_catio.naming.BOX_TYPE_RE``.
BOX_TYPE_RE = re.compile(r"(E[PQR]P?\d{4})")

COUPLER = "coupler"
BOX = "box"
SLAVE = "slave"

#: Where an XMLbuilder support module keeps its IOC definitions.
MAKE_IOCS = Path("etc/makeIocs")

#: ``type_rev`` looks like ``"EL3104 rev 0x00120000"``; the revision is optional.
_TYPE_REV_RE = re.compile(r"^(?P<type>\S+)(?:\s+rev\s+(?P<rev>\S+))?\s*$")

#: A declared ``DEVICE=`` split into its coupler label and its ``MOD`` part.
#: Greedy, so the *last* ``:MOD`` separates them. ``mod`` may be non-numeric
#: (``MODSAM3``), in which case it is an opaque label and no position check
#: applies.
_DEVICE_MOD_RE = re.compile(r"^(?P<label>.+):MOD(?P<mod>.+)$")


@dataclass(frozen=True)
class Slave:
    """One EtherCAT slave, located on the bus and bound to its builder entity.

    :param node: 1-based coupler/box ordinal; 0 for slaves ahead of the first.
    :param position: 0 on the coupler itself, then 1, 2, ... along its terminals.
    :param type_name: CANopen type, e.g. ``"EL3104"`` or ``"EL2024-0010"``.
    :param revision: EtherCAT revision as an int, or None when ``type_rev``
        carried no ``rev`` part.
    :param slave_name: the ``EthercatSlave`` ``name=``, which is also the asyn
        port an ``auto_*`` entity names in ``PORT=``.
    :param category: :data:`COUPLER`, :data:`BOX` or :data:`SLAVE`.
    :param entity_type: the bound ``auto_*`` element name, e.g. ``auto_EL3104``.
    :param entity_name: that entity's ``name=``.
    :param declared_device: that entity's ``DEVICE=`` -- the legacy PV prefix.
    """

    node: int
    position: int
    type_name: str
    revision: int | None
    slave_name: str
    category: str
    entity_type: str | None = None
    entity_name: str | None = None
    declared_device: str | None = None

    @property
    def is_known(self) -> bool:
        """True when a bound entity has a leaf translation table.

        >>> Slave(1, 1, "EL3104", None, "P", SLAVE, "auto_EL3104").is_known
        True
        >>> Slave(1, 1, "EL2595", None, "P", SLAVE, "auto_EL2595").is_known
        False
        >>> Slave(1, 0, "EK1100", None, "P", COUPLER).is_known
        False
        """
        return self.entity_type in KNOWN_ENTITY_TYPES


@dataclass
class Chain:
    """One scanner IOC's EtherCAT bus, and the fastcs-catio IOC replacing it."""

    scanner_ioc: str
    domain: str
    ordinal: int
    slaves: list[Slave] = field(default_factory=list)
    labels: dict[int, str | None] = field(default_factory=dict)

    @property
    def catio_ioc(self) -> str:
        """The fastcs-catio IOC name.

        >>> Chain("BL21I-VA-IOC-01", "BL21I-VA", 1).catio_ioc
        'BL21I-VA-CATIO-01'
        """
        return catio_ioc_name(self.scanner_ioc)

    @property
    def services_folder(self) -> str:
        """The services-repo folder holding that IOC.

        >>> Chain("BL21I-VA-IOC-01", "BL21I-VA", 1).services_folder
        'bl21i-va-catio-01'
        """
        return self.catio_ioc.lower()

    @property
    def node_prefix(self) -> str:
        """``name_mappings.node_prefix`` for this chain.

        Absolute on purpose. fastcs-catio's default,
        ``"{device_prefix}:E1RIO{:02d}"``, would make a four-segment module path
        and trip the shortening guard -- see :func:`predict_prefixes`.

        >>> Chain("BL21I-VA-IOC-01", "BL21I-VA", 2).node_prefix
        'BL21I-VA-E2RIO-{:02d}'
        """
        return f"{self.domain}-E{self.ordinal}RIO-{{:02d}}"

    @property
    def device_prefix(self) -> str:
        """``name_mappings.device_prefix``; the fastcs-catio default."""
        return "{id}:ETH{:02d}"

    @property
    def module_prefix(self) -> str:
        """``name_mappings.module_prefix``, keyed on the terminal group alias."""
        return "{node_prefix}:{group_alias}{:02d}"

    def name_mappings(self) -> dict[str, str]:
        """The three templates, ready for ``config/fastcs.yaml``.

        The generated IOC and the names predicted here **must** come from this
        one source: a divergence points every rewritten PV at nothing.

        >>> Chain("BL21I-VA-IOC-01", "BL21I-VA", 1).name_mappings()["node_prefix"]
        'BL21I-VA-E1RIO-{:02d}'
        """
        return {
            "device_prefix": self.device_prefix,
            "node_prefix": self.node_prefix,
            "module_prefix": self.module_prefix,
        }


def catio_ioc_name(scanner_ioc: str) -> str:
    """The fastcs-catio IOC name replacing *scanner_ioc*.

    Only a whole ``IOC`` dash-segment is renamed, so a beamline that happens to
    contain the letters elsewhere is left alone.

    >>> catio_ioc_name("BL21I-DI-IOC-01")
    'BL21I-DI-CATIO-01'
    """
    parts = ["CATIO" if part == "IOC" else part for part in scanner_ioc.split("-")]
    return "-".join(parts)


class UnresolvedMap(dict[str, tuple[str, str, str | None]]):
    """``unresolved`` for :class:`~builder2ibek.catio.substitute.Substituter`.

    A plain ``dict`` of full legacy PV -> ``(code, message, chain)``, extended
    with *prefix* entries. A terminal whose ``auto_*`` entity type has no leaf
    table has unknowable record suffixes, so it cannot be enumerated key by key;
    registering its PV prefix makes every reference beneath it resolve to the
    same diagnostic.

    Only :meth:`get` consults the prefixes -- that is the sole method
    ``Substituter`` calls -- so ``in``, ``[]`` and iteration stay exact.

    >>> u = UnresolvedMap()
    >>> u.add_prefix("BL21I-DI-LED-01", ("unknown-entity-type", "no table", "X"))
    >>> u.get("BL21I-DI-LED-01:CHANNEL1:OUTPUT")[0]
    'unknown-entity-type'
    >>> u.get("BL21I-DI-LED-011:CHANNEL1:OUTPUT") is None
    True
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: PV prefix -> the entry every PV beneath it resolves to.
        self.prefixes: dict[str, tuple[str, str, str | None]] = {}

    def add_prefix(self, prefix: str, entry: tuple[str, str, str | None]) -> None:
        """Make every PV under *prefix* resolve to *entry*."""
        self.prefixes[prefix] = entry

    def get(  # type: ignore[override]
        self, key: str, default: tuple[str, str, str | None] | None = None
    ) -> tuple[str, str, str | None] | None:
        """Exact match first, then the longest registered prefix."""
        entry = super().get(key)
        if entry is not None:
            return entry
        best: str | None = None
        for prefix in self.prefixes:
            if not key.startswith(prefix + ":"):
                continue
            if best is None or len(prefix) > len(best):
                best = prefix
        return self.prefixes[best] if best is not None else default


# -- parsing -----------------------------------------------------------------


def _locate(type_names: Sequence[str]) -> list[tuple[int, int, str]]:
    """Assign ``(node, position, category)`` to each slave, in bus order.

    A local copy of ``fastcs_catio.naming._locate``, duplicated because this
    module must import cleanly without `fastcs_catio` (pytest collects `src`
    with ``--doctest-modules``). ``test_catio_chains.py`` asserts the two agree
    on every sample chain, which is what stops them drifting.

    >>> _locate(["EK1100", "EL3104", "EK1122", "EL1014"])
    [(1, 0, 'coupler'), (1, 1, 'slave'), (1, 2, 'slave'), (1, 3, 'slave')]
    >>> _locate(["EK1100", "EL3104", "EK1100", "EL1014"])[2]
    (2, 0, 'coupler')
    """
    located: list[tuple[int, int, str]] = []
    node = 0
    position = 0
    for type_name in type_names:
        category = SLAVE
        if type_name == EXTENSION_TYPE and node == 0:
            position += 1
        if type_name == COUPLER_TYPE:
            category = COUPLER
            node += 1
            position = 0
        if BOX_TYPE_RE.match(type_name) is not None:
            category = BOX
            node += 1
            position = 0
        located.append((node, position, category))
        position += 1
    return located


def _split_type_rev(type_rev: str) -> tuple[str, int | None]:
    """Split an ``EthercatSlave`` ``type_rev`` into type name and revision.

    >>> _split_type_rev("EL3104 rev 0x00120000")
    ('EL3104', 1179648)
    >>> _split_type_rev("EL2024-0010")
    ('EL2024-0010', None)
    """
    match = _TYPE_REV_RE.match(type_rev.strip())
    if match is None:  # pragma: no cover - type_rev is always non-empty in practice
        return type_rev.strip(), None
    revision = match.group("rev")
    if revision is None:
        return match.group("type"), None
    try:
        return match.group("type"), int(revision, 0)
    except ValueError:
        return match.group("type"), None


def is_scanner(builder: Builder) -> bool:
    """True when this IOC declares an EtherCAT master, and so owns a chain.

    >>> from builder2ibek.builder import Builder
    >>> b = Builder()
    >>> b.load_string('<components arch="linux-x86_64">'
    ...               '<ethercat.EthercatMaster name="ECATM"/></components>')
    >>> is_scanner(b)
    True
    """
    return any(
        element.module == "ethercat" and element.name == "EthercatMaster"
        for element in builder.elements
    )


def _bind_entities(builder: Builder) -> dict[str, list]:
    """``EthercatSlave`` name -> the ``auto_*`` entities naming it in ``PORT=``."""
    by_port: dict[str, list] = {}
    for element in builder.elements:
        if element.module == "ethercat" and element.name.startswith("auto_"):
            by_port.setdefault(element.attributes.get("PORT", ""), []).append(element)
    return by_port


def _derive_labels(chain: Chain, log: DiagnosticLog) -> None:
    """Fill ``chain.labels`` from the ``DEVICE=`` of each coupler's terminals.

    The label is the unanimous part before ``:MOD``. Entities whose ``DEVICE``
    has no ``:MOD`` part -- ``BL21I-OP-LED-01``, ``BL21I-MO-PIEZO-01`` -- name a
    device rather than a bus slot and are ignored, with ``device-without-mod``.
    ``<!--Start of ...-->`` comments are ignored entirely: they are unvalidatable
    free text and are simply wrong in `BL21I-VA-IOC-06`.
    """
    candidates: dict[int, dict[str, list[Slave]]] = {}
    for slave in chain.slaves:
        candidates.setdefault(slave.node, {})
        device = slave.declared_device
        if not device:
            continue
        match = _DEVICE_MOD_RE.match(device)
        if match is None:
            log.add(
                "device-without-mod",
                f"{slave.entity_type} declares DEVICE={device!r}, which has no "
                "':MOD' part, so it is ignored when deriving the coupler label",
                chain=chain.scanner_ioc,
                entity=slave.entity_name,
                attribute="DEVICE",
            )
            continue
        candidates[slave.node].setdefault(match.group("label"), []).append(slave)

    for node, found in candidates.items():
        if len(found) == 1:
            chain.labels[node] = next(iter(found))
        elif not found:
            chain.labels[node] = None
            if node == 0:
                # Slaves ahead of the first coupler. There is no coupler to
                # label, so nothing is missing.
                continue
            log.add(
                "unlabelled-coupler",
                f"node {node} has no entity declaring a 'LABEL:MODn' DEVICE, so "
                "no coupler label can be derived; chain-derived aliases for its "
                "terminals will not be registered",
                chain=chain.scanner_ioc,
            )
        else:
            chain.labels[node] = None
            log.add(
                "coupler-label-conflict",
                f"node {node} carries entities declaring more than one coupler "
                f"label: {', '.join(sorted(found))}",
                chain=chain.scanner_ioc,
            )

    seen: dict[str, list[int]] = {}
    for node, label in chain.labels.items():
        if label:
            seen.setdefault(label, []).append(node)
    for label, nodes in seen.items():
        if len(nodes) > 1:
            log.add(
                "duplicate-coupler-label",
                f"label {label} is derived for nodes {nodes}; their declared PV "
                "names stay distinct, but chain-derived aliases that collide "
                "will be dropped",
                chain=chain.scanner_ioc,
            )


def _check_declarations(chain: Chain, log: DiagnosticLog) -> None:
    """Cross-check each bound entity against the slave it landed on."""
    for slave in chain.slaves:
        if slave.entity_type is None:
            continue
        if slave.entity_type in TERMINALS:
            expected = TERMINALS[slave.entity_type].terminal_type
            if expected != slave.type_name:
                log.add(
                    "slave-type-mismatch",
                    f"slave {slave.slave_name} is a {slave.type_name} but is "
                    f"bound to {slave.entity_type}, which describes a "
                    f"{expected}; the {expected} leaf table is used anyway",
                    chain=chain.scanner_ioc,
                    entity=slave.entity_name,
                    attribute="PORT",
                )
        match = _DEVICE_MOD_RE.match(slave.declared_device or "")
        if match is None:
            continue
        mod = match.group("mod")
        if mod.isdigit() and int(mod) != slave.position:
            log.add(
                "device-mod-mismatch",
                f"{slave.entity_name or slave.entity_type} declares "
                f"DEVICE={slave.declared_device!r} but sits at bus position "
                f"{slave.position} of node {slave.node}; the declared name is "
                "kept and the chain-derived alias is registered as well",
                chain=chain.scanner_ioc,
                entity=slave.entity_name,
                attribute="DEVICE",
            )


def _chain_from_builder(
    builder: Builder, log: DiagnosticLog, *, ordinal: int
) -> Chain | None:
    """Build a :class:`Chain` from an already-loaded scanner :class:`Builder`."""
    if not is_scanner(builder):
        return None
    scanner_ioc = builder.name
    chain = Chain(
        scanner_ioc=scanner_ioc,
        domain=domain_of(scanner_ioc),
        ordinal=ordinal,
    )
    elements = [
        e
        for e in builder.elements
        if e.module == "ethercat" and e.name == "EthercatSlave"
    ]
    by_port = _bind_entities(builder)
    type_names = [
        _split_type_rev(e.attributes.get("type_rev", ""))[0] for e in elements
    ]
    for element, (node, position, category) in zip(
        elements, _locate(type_names), strict=True
    ):
        type_name, revision = _split_type_rev(element.attributes.get("type_rev", ""))
        slave_name = element.attributes.get("name", "")
        # Only the first binding is modelled: no slave in any DLS tree examined
        # carries two auto_* entities, and Slave holds a single entity.
        entities = by_port.get(slave_name, [])
        entity = entities[0] if entities else None
        chain.slaves.append(
            Slave(
                node=node,
                position=position,
                type_name=type_name,
                revision=revision,
                slave_name=slave_name,
                category=category,
                entity_type=entity.name if entity else None,
                entity_name=entity.attributes.get("name") if entity else None,
                declared_device=entity.attributes.get("DEVICE") if entity else None,
            )
        )
    _derive_labels(chain, log)
    _check_declarations(chain, log)
    return chain


def parse_chain(xml: Path, log: DiagnosticLog, *, ordinal: int) -> Chain | None:
    """Parse one builder XML into a :class:`Chain`.

    :param xml: the IOC's builder XML. Its stem is taken as the IOC name.
    :param log: diagnostics are appended here; parsing never raises for a
        malformed chain.
    :param ordinal: this chain's ``E{n}RIO`` number within its domain -- see
        :func:`discover_chains`, which allocates them.
    :returns: the chain, or None when the IOC declares no EtherCAT master.
    """
    builder = Builder()
    builder.load(xml)
    return _chain_from_builder(builder, log, ordinal=ordinal)


def domain_of(ioc_name: str) -> str:
    """The first two dash-segments of an IOC name.

    >>> domain_of("BL21I-VA-IOC-01")
    'BL21I-VA'
    """
    return "-".join(ioc_name.split("-")[:2])


def discover_chains(
    builder_root: Path,
    log: DiagnosticLog,
    *,
    sticky: dict[str, int] | None = None,
) -> list[Chain]:
    """Find and parse every scanner chain under *builder_root*.

    :param builder_root: either a BUILDER support module root (its XMLs are then
        read from ``etc/makeIocs``) or a directory that already *is* an
        ``etc/makeIocs``. Which it is, is detected: the ``etc/makeIocs``
        subdirectory is used when present, else *builder_root* itself.
    :param log: diagnostics from parsing every chain.
    :param sticky: ``catio_ioc -> ordinal`` read back from a services repo by
        :func:`builder2ibek.catio.services.read_sticky_ordinals`. Honoured
        exactly; only chains absent from it get a freshly allocated ordinal.
        Renumbering an already-generated chain would repoint every PV that a
        previous run rewrote at a name nothing creates. A pin whose scanner XML
        is *gone* still reserves its ordinal: that IOC is deployed and answering
        on those PVs whether or not its builder XML survives.
    :returns: the chains, sorted by domain then scanner IOC name.
    :raises ValueError: when *sticky* gives two IOCs of one domain the same
        ordinal. That is a corrupt services repo, not a defect in any chain, so
        it is not a diagnostic.

    Ordinals are allocated per domain (``BL21I-VA``), in ascending scanner-IOC
    name order, from the lowest positive integers left free by *sticky*.
    """
    search = builder_root / MAKE_IOCS
    if not search.is_dir():
        search = builder_root

    builders: dict[str, Builder] = {}
    for xml in sorted(search.glob("*.xml")):
        builder = Builder()
        builder.load(xml)
        if is_scanner(builder):
            builders[builder.name] = builder

    sticky = sticky or {}
    ordinals: dict[str, int] = {}
    by_domain: dict[str, list[str]] = {}
    for scanner_ioc in sorted(builders):
        by_domain.setdefault(domain_of(scanner_ioc), []).append(scanner_ioc)

    for domain, scanners in by_domain.items():
        taken: dict[int, str] = {}
        by_catio_ioc = {catio_ioc_name(scanner): scanner for scanner in scanners}
        # Every pin in this domain reserves its ordinal, including *orphans* --
        # a services folder whose scanner XML has since been renamed or retired
        # is still deployed and still owns its E{n}RIO names. Handing a live
        # chain an orphan's ordinal would put two IOCs on identical PVs.
        for catio_ioc, pinned in sorted(sticky.items()):
            if domain_of(catio_ioc) != domain:
                continue
            if pinned in taken:
                raise ValueError(
                    f"services repo pins ordinal {pinned} to both "
                    f"{taken[pinned]} and {catio_ioc} in "
                    f"domain {domain}; fix the duplicate node_prefix in their "
                    "config/fastcs.yaml before re-running"
                )
            taken[pinned] = catio_ioc
            if catio_ioc in by_catio_ioc:
                ordinals[by_catio_ioc[catio_ioc]] = pinned
        next_free = 1
        for scanner_ioc in scanners:
            if scanner_ioc in ordinals:
                continue
            while next_free in taken:
                next_free += 1
            taken[next_free] = catio_ioc_name(scanner_ioc)
            ordinals[scanner_ioc] = next_free
            next_free += 1

    chains: list[Chain] = []
    for domain in sorted(by_domain):
        for scanner_ioc in by_domain[domain]:
            chain = _chain_from_builder(
                builders[scanner_ioc], log, ordinal=ordinals[scanner_ioc]
            )
            if chain is not None:
                chains.append(chain)
    return chains


# -- name prediction ---------------------------------------------------------

_NO_FASTCS = (
    "fastcs_catio is required to predict fastcs-catio PV names. It is "
    "deliberately absent from builder2ibek's own environment -- its release "
    "pins a fastcs version that no longer exists on PyPI, so adding it breaks "
    "`uv lock`. Run this command with the side venv instead, e.g.\n"
    "    .venv-catio/bin/python -m builder2ibek catio ...\n"
    "(see .catio-spec/HANDOFF.md)"
)


def _is_writable(access: str | None) -> bool:
    """FastCS's own read/write test, from ``AdsItemBase.readonly``.

    Duplicated rather than imported because it is a property of an instantiated
    ADS item, which needs a live controller.

    >>> _is_writable("Read/Write"), _is_writable("Read-only"), _is_writable(None)
    (True, False, False)
    """
    if access is None:
        return False
    lowered = access.lower()
    return "write" in lowered or lowered in ("rw", "wo")


def _fastcs_attributes(type_name: str) -> dict[str, bool]:
    """The PDO attributes fastcs-catio gives *type_name* -> whether each is R/W.

    Read straight from ``terminal_types.yaml`` via fastcs-catio's own loader, so
    :mod:`builder2ibek.catio.leaves` is checked against the library rather than
    against a second hand-maintained copy of it. Only *selected* symbol nodes
    appear, matching ``catio_dynamic_controller.create_terminal_controller``;
    CoE and runtime attributes are deliberately excluded, as no leaf table maps
    to one.

    :raises ImportError: when `fastcs_catio` is not installed.
    """
    try:
        from fastcs_catio.terminal_config import (
            get_terminal_type,
            symbol_to_fastcs_name,
        )
    except ImportError as err:  # pragma: no cover - depends on the environment
        raise ImportError(_NO_FASTCS) from err

    attributes: dict[str, bool] = {}
    for symbol in get_terminal_type(type_name).symbol_nodes:
        if not symbol.selected:
            continue
        channels = symbol.channel_indices if symbol.channels > 1 else [None]
        for channel in channels:
            attributes[symbol_to_fastcs_name(symbol, channel)] = _is_writable(
                symbol.access
            )
    return attributes


def predict_prefixes(chain: Chain, log: DiagnosticLog) -> dict[tuple[int, int], str]:
    """``(node, position)`` -> the PV prefix fastcs-catio will give that slave.

    Delegates the naming rule entirely to ``fastcs_catio.naming``: reproducing
    it here would let the two drift, and a drift points every rewritten PV at a
    name nothing creates. ``predict_chain`` is used rather than
    ``predict_names`` -- it returns the same prefixes plus the ``path``
    segments the shortening guard needs.

    The **shortening guard**: FastCS truncates an attribute name that will not
    fit the 60-character EPICS PV limit at its controller's prefix. With
    fastcs-catio's default four-segment ``node_prefix`` the budget drops far
    enough to truncate ``ai_standard_channel_1_value``, collapsing all twelve
    EL3104 attributes onto one name and crashing the IOC at startup. Every leaf
    this chain will emit is therefore checked against fastcs-catio's own
    ``max_attribute_name_length`` / ``shorten_fastcs_name`` at the prefix
    actually emitted; any that shortens raises ``shortened-leaf``.

    The **leaf check**: every leaf is looked up in the attribute set
    fastcs-catio will actually build for the slave's *own* type
    (:func:`_fastcs_attributes`), not for the type its ``auto_*`` entity claims.
    A leaf that is absent, or whose writability disagrees (which decides the
    ``_RBV`` suffix), would be rewritten to a PV the new IOC never creates, so
    it raises ``leaf-type-mismatch``. This is what keeps
    :mod:`builder2ibek.catio.leaves` honest against ``terminal_types.yaml``, and
    what catches an entity bound to the wrong terminal -- the case
    ``slave-type-mismatch`` only warns about.

    :returns: the prefixes, or ``{}`` when the chain names a terminal type
        fastcs-catio does not know (``unknown-terminal-type``).
    :raises ImportError: when `fastcs_catio` is not installed.
    """
    try:
        from catio_terminals.utils import shorten_fastcs_name
        from fastcs_catio.catio_controller import CATioNameMappings
        from fastcs_catio.naming import (
            ChainEntry,
            UnknownTerminalTypeError,
            predict_chain,
        )
        from fastcs_catio.utils import max_attribute_name_length
    except ImportError as err:  # pragma: no cover - depends on the environment
        raise ImportError(_NO_FASTCS) from err

    mappings = CATioNameMappings(
        device_prefix=chain.device_prefix,
        node_prefix=chain.node_prefix,
        module_prefix=chain.module_prefix,
    )
    entries = [ChainEntry(s.type_name, s.revision) for s in chain.slaves]
    try:
        predicted = predict_chain(
            entries, mappings, root_id=chain.catio_ioc, strict=True
        )
    except UnknownTerminalTypeError as err:
        log.add(
            "unknown-terminal-type",
            f"{err.args[0] if err.args else err}",
            chain=chain.scanner_ioc,
        )
        return {}

    for slave in chain.slaves:
        if not slave.is_known:
            continue
        path = predicted[(slave.node, slave.position)].path
        actual = _fastcs_attributes(slave.type_name)
        for leaf in leaf_translations(slave.entity_type or "").values():
            if leaf.fastcs_name not in actual:
                log.add(
                    "leaf-type-mismatch",
                    f"{slave.entity_type} translates a legacy record to "
                    f"{leaf.fastcs_name!r}, but the {slave.type_name} on port "
                    f"{slave.slave_name} has no such fastcs-catio attribute, so "
                    "the rewritten PV would not exist",
                    chain=chain.scanner_ioc,
                    entity=slave.entity_name,
                )
                continue
            if actual[leaf.fastcs_name] != leaf.writable:
                direction = "read-only" if leaf.writable else "read/write"
                log.add(
                    "leaf-type-mismatch",
                    f"{slave.entity_type} treats {leaf.fastcs_name!r} as "
                    f"{'read/write' if leaf.writable else 'read-only'}, but on "
                    f"the {slave.type_name} at port {slave.slave_name} it is "
                    f"{direction}, so the '_RBV' rule would pick a PV that does "
                    "not exist",
                    chain=chain.scanner_ioc,
                    entity=slave.entity_name,
                )
                continue
            budget = max_attribute_name_length(path, is_rw=leaf.writable)
            shortened = shorten_fastcs_name(leaf.fastcs_name, budget)
            if shortened != leaf.fastcs_name:
                log.add(
                    "shortened-leaf",
                    f"at prefix {':'.join(path)} FastCS shortens "
                    f"{leaf.fastcs_name!r} to {shortened!r} (budget {budget}); "
                    "the emitted PV would not exist and colliding leaves crash "
                    "the IOC at startup -- shorten node_prefix",
                    chain=chain.scanner_ioc,
                    entity=slave.entity_name,
                )

    return {key: slave.prefix for key, slave in predicted.items()}


# -- substitution map --------------------------------------------------------

#: A pending map entry: either a resolved replacement or a reason it is not one.
_Entry = tuple[str, object]
_SUB = "sub"
_BAD = "bad"


def _register(
    table: dict[str, tuple[_Entry, str]],
    ambiguous: dict[str, str],
    key: str,
    entry: _Entry,
    chain: str,
) -> None:
    """Add *key* -> *entry*, recording a genuine clash instead of overwriting.

    Two entries agree when they are the same replacement, or when both are
    unresolved for the same reason -- ``AL_STATE`` has no fastcs equivalent
    whichever terminal declared it, so a duplicate is not an ambiguity.
    """
    existing = table.get(key)
    if existing is None:
        table[key] = (entry, chain)
        return
    (kind, value), owner = existing
    if kind == entry[0] and value == entry[1]:
        return
    ambiguous[key] = chain if owner == chain else f"{owner} and {chain}"


def _dead_prefixes(chain: Chain, *, skip: set[str]) -> list[str]:
    """Every PV prefix a *failed* chain owns, so references to it can be caught.

    Both families a live chain would have registered: the coupler labels a
    chain-derived alias is built from, and each terminal's declared ``DEVICE=``.
    Labels already claimed by a converted chain are skipped -- that chain's own
    keys are authoritative and must not be shadowed.

    >>> chain = Chain("BL21I-DI-IOC-01", "BL21I-DI", 1)
    >>> chain.labels = {1: "BL21I-DI-ERIO-01"}
    >>> chain.slaves = [Slave(1, 1, "EL2595", None, "P", SLAVE,
    ...                       "auto_EL2595", "LED", "BL21I-DI-LED-01")]
    >>> _dead_prefixes(chain, skip=set())
    ['BL21I-DI-ERIO-01', 'BL21I-DI-LED-01']
    """
    prefixes = {label for label in chain.labels.values() if label}
    prefixes |= {s.declared_device for s in chain.slaves if s.declared_device}
    return sorted(prefixes - skip)


def build_substituter(chains: list[Chain], log: DiagnosticLog) -> Substituter:
    """Assemble the substitution map for every clean chain.

    Chains that already recorded an ERROR (``log.failed_chains()``) contribute
    nothing: no substitutions, and later no fastcs-catio IOC. Under ``--strict``
    that includes chains whose only problem was ``device-mod-mismatch``.

    Two passes, so that a declared name is never displaced by a chain-derived
    alias -- see the module docstring for why that matters.

    :returns: a :class:`~builder2ibek.catio.substitute.Substituter` whose
        ``unresolved`` is an :class:`UnresolvedMap`. After running it over every
        consumer IOC, call :func:`report_unused_ambiguities`.
    """
    failed = log.failed_chains()
    live = [chain for chain in chains if chain.scanner_ioc not in failed]

    prefixes: dict[str, dict[tuple[int, int], str]] = {}
    for chain in live:
        prefixes[chain.scanner_ioc] = predict_prefixes(chain, log)
    failed = log.failed_chains()
    live = [c for c in live if c.scanner_ioc not in failed and prefixes[c.scanner_ioc]]
    live_names = {chain.scanner_ioc for chain in live}
    dead = [chain for chain in chains if chain.scanner_ioc not in live_names]

    known_labels: dict[str, str] = {}
    for chain in live:
        for label in chain.labels.values():
            if not label:
                continue
            owner = known_labels.setdefault(label, chain.scanner_ioc)
            if owner != chain.scanner_ioc:
                for claimant in (owner, chain.scanner_ioc):
                    log.add(
                        "unknown-chain-label",
                        f"coupler label {label} is declared by both {owner} and "
                        f"{chain.scanner_ioc}; a reference to it cannot be "
                        "resolved to one terminal",
                        chain=claimant,
                    )

    declared: dict[str, tuple[_Entry, str]] = {}
    derived: dict[str, tuple[_Entry, str]] = {}
    # Kept apart so that an ambiguity among the positional aliases can never
    # discard the declared name of the same PV.
    amb_declared: dict[str, str] = {}
    amb_derived: dict[str, str] = {}
    # device prefix -> (scanner IOC, entity type, terminal type, entity name)
    unknown_prefixes: dict[str, tuple[str, str, str, str | None]] = {}

    for chain in live:
        chain_prefixes = prefixes[chain.scanner_ioc]
        for slave in chain.slaves:
            if slave.category == COUPLER or slave.entity_type is None:
                continue
            device = slave.declared_device or ""
            entity_type = slave.entity_type
            if entity_type not in KNOWN_ENTITY_TYPES:
                # Suffixes unknowable, so only the authoritative declared prefix
                # is registered -- a chain-derived alias could not be enumerated
                # and would risk shadowing a real neighbour's declared name.
                if device:
                    unknown_prefixes[device] = (
                        chain.scanner_ioc,
                        entity_type,
                        slave.type_name,
                        slave.entity_name,
                    )
                continue
            new_prefix = chain_prefixes[(slave.node, slave.position)]
            label = chain.labels.get(slave.node)
            forms: list[tuple[dict, dict, str]] = []
            if device:
                # Any non-empty DEVICE= is registered, `:MOD`-shaped or not.
                # The `LABEL:MODn` shape is only needed to *derive* a coupler
                # label and to cross-check bus position; the declared name is
                # the record the legacy IOC created either way, so gating on the
                # shape silently dropped the real PVs of terminals named after
                # the device they drive (`BL21I-OP-LED-01:CHANNEL1:OUTPUT`).
                forms.append((declared, amb_declared, device))
            if label:
                forms.append((derived, amb_derived, f"{label}:MOD{slave.position}"))
            for table, ambiguous, prefix in forms:
                for suffix, leaf in leaf_translations(entity_type).items():
                    value = NewPv(
                        read=f"{new_prefix}:{pv_leaf(leaf, reading=True)}",
                        write=f"{new_prefix}:{pv_leaf(leaf, reading=False)}",
                    )
                    _register(
                        table,
                        ambiguous,
                        f"{prefix}:{suffix}",
                        (_SUB, value),
                        chain.scanner_ioc,
                    )
                for suffix in unmapped_suffixes(entity_type):
                    _register(
                        table,
                        ambiguous,
                        f"{prefix}:{suffix}",
                        (_BAD, "unmapped-suffix"),
                        chain.scanner_ioc,
                    )

    subs: SubstitutionMap = {}
    owners: dict[str, str] = {}
    unresolved = UnresolvedMap()

    def emit(key: str, entry: _Entry, chain: str) -> None:
        owners[key] = chain
        if entry[0] == _SUB:
            subs[key] = entry[1]  # type: ignore[assignment]
        else:
            unresolved[key] = (
                "unmapped-suffix",
                f"{key} is a legacy record with no fastcs-catio equivalent, so "
                "the new IOC will not create it; the reference must be removed "
                "or repointed by hand",
                chain,
            )

    for key, (entry, chain_name) in declared.items():
        if key not in amb_declared:
            emit(key, entry, chain_name)
    for key, (entry, chain_name) in derived.items():
        # Declared names win outright: they are the records the legacy IOC
        # really created, so a colliding positional alias is provably a guess.
        if key in declared or key in amb_declared or key in amb_derived:
            continue
        emit(key, entry, chain_name)

    ambiguities = dict(amb_declared)
    for key, chain_name in amb_derived.items():
        if key not in declared and key not in amb_declared:
            ambiguities[key] = chain_name
    for key, chain_name in ambiguities.items():
        owners.setdefault(key, chain_name.split(" and ")[0])
        unresolved[key] = (
            "ambiguous-legacy-pv",
            f"{key} maps to more than one fastcs-catio PV (declared on "
            f"{chain_name}), so it was dropped rather than rewritten to the "
            "wrong terminal",
            chain_name.split(" and ")[0],
        )

    # A chain that failed *before* substitution contributes no keys at all, so
    # without this its consumers would sail through: `LEGACY_PV_RE` only
    # recognises names carrying an `-ERIO-` segment, and a declared `DEVICE=`
    # need not have one (`BL21I-DI-LED-01`). The consumer would then be written
    # with a dangling legacy PV and no diagnostic. Registering the failed
    # chain's own prefixes makes every such reference fail loudly, attributed to
    # the chain that has to be fixed. Registered before the live entries below,
    # so a live chain always wins a prefix they somehow share.
    for chain in dead:
        for prefix in _dead_prefixes(chain, skip=set(known_labels)):
            unresolved.add_prefix(
                prefix,
                (
                    "unknown-chain-label",
                    f"{prefix} belongs to chain {chain.scanner_ioc}, which failed "
                    "to convert, so no fastcs-catio name can be predicted for it; "
                    "fix that chain's errors and re-run",
                    chain.scanner_ioc,
                ),
            )

    for prefix, (chain_name, entity_type, type_name, entity_name) in sorted(
        unknown_prefixes.items()
    ):
        where = f" (entity {entity_name})" if entity_name else ""
        unresolved.add_prefix(
            prefix,
            (
                "unknown-entity-type",
                f"{prefix} is declared by {entity_type}{where}, a {type_name} "
                "terminal that builder2ibek.catio.leaves has no translation "
                "table for, so its legacy record suffixes are unknown and no "
                f"fastcs-catio name can be predicted; add {type_name} to "
                "leaves.TERMINALS to convert this chain",
                chain_name,
            ),
        )

    return Substituter(subs, owners, unresolved, known_labels)


def report_unused_ambiguities(
    substituter: Substituter, log: DiagnosticLog
) -> list[str]:
    """Downgrade ambiguities that nothing referenced, after substitution.

    ``build_substituter`` cannot know whether a dropped key matters, so it
    registers every ambiguity at ``ambiguous-legacy-pv`` (ERROR) and
    ``Substituter`` raises it only when a consumer actually names one. Call this
    once at the end of the run: every ambiguity whose diagnostic never fired is
    re-reported at ``ambiguous-legacy-pv-unused`` (WARNING), so the report is
    complete without failing a chain over a name nobody uses.

    :returns: the legacy PVs downgraded, sorted.
    """
    fired = {d.message for d in log if d.code == "ambiguous-legacy-pv"}
    downgraded: list[str] = []
    for key, (code, message, chain) in sorted(substituter.unresolved.items()):
        if code != "ambiguous-legacy-pv" or message in fired:
            continue
        log.add("ambiguous-legacy-pv-unused", message, chain=chain)
        downgraded.append(key)
    return downgraded


def chain_by_ioc(chains: Iterable[Chain]) -> dict[str, Chain]:
    """Index chains by their scanner IOC name.

    >>> sorted(chain_by_ioc([Chain("BL21I-VA-IOC-01", "BL21I-VA", 1)]))
    ['BL21I-VA-IOC-01']
    """
    return {chain.scanner_ioc: chain for chain in chains}
