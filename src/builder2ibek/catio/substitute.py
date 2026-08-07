"""Rewriting legacy EtherCAT PV references onto their fastcs-catio names.

This module is deliberately **pure**: it does no file I/O, never imports
`fastcs_catio`, and knows nothing about EtherCAT chains beyond the four
dictionaries its constructor is handed. :mod:`builder2ibek.catio.chains` builds
those dictionaries; this module only applies them.

Substitution is **token-wise on parsed entity values**, never on XML text. A
value such as ``"BL21I-DI-ERIO-10:MOD1:INPUT1:VALUE CP"`` is split on
whitespace runs, only whole tokens that are exact keys of the substitution map
are replaced, and everything else -- including the trailing EPICS link flags --
is preserved byte for byte. Keys are the *full* legacy PV including the record
suffix, because a prefix-only substitution would be unsafe: `DEVICE=` names are
ambiguous between terminals and only the leaf disambiguates them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from builder2ibek.catio.diagnostics import DiagnosticLog

__all__ = [
    "INPUT_ATTR_RE",
    "LEGACY_PV_RE",
    "OUTPUT_ATTR_RE",
    "READ_FLAGS",
    "WRITE_FLAGS",
    "NewPv",
    "SubstitutionMap",
    "Substituter",
    "link_is_reading",
]


#: A token that looks like a legacy EtherCAT PV: a hyphenated device name
#: containing an ``ERIO`` segment, followed by at least one ``:``-separated
#: record suffix. The colon is required -- bare ``ERIO`` words in free text
#: must not be mistaken for PV references.
LEGACY_PV_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-ERIO-[A-Za-z0-9]+:\S+$")

#: EPICS link flags that make the link *read* the target.
READ_FLAGS = frozenset({"CP", "CPP", "MS", "MSS", "MSI"})

#: EPICS link flags that make the link *write* to the target.
WRITE_FLAGS = frozenset({"PP", "NPP"})

#: Attribute names that name an output link.
OUTPUT_ATTR_RE = re.compile(r"(?i)(^|_)(out|dol|output)(\d*)($|_)")

#: Attribute names that name an input link.
INPUT_ATTR_RE = re.compile(r"(?i)(^|_)(inp|input|in)(\d*)($|_)")


@dataclass(frozen=True)
class NewPv:
    """The replacement PVs for one legacy PV.

    FastCS gives a read/write attribute two PVs -- the setpoint under its own
    name and a readback suffixed ``_RBV`` -- so which one a consumer should use
    depends on the direction of the link that references it.

    :param read: full new PV a reader should use.
    :param write: full new PV a writer should use.
    """

    read: str
    write: str

    @classmethod
    def same(cls, name: str) -> NewPv:
        """A read-only signal, where both directions use the same PV.

        >>> NewPv.same("BL21I-VA-E1RIO-01:24VDI01:Channel1")
        NewPv(read='BL21I-VA-E1RIO-01:24VDI01:Channel1', write='BL21I-VA-E1RIO-01:24VDI01:Channel1')
        """  # noqa: E501
        return cls(read=name, write=name)

    @property
    def writable(self) -> bool:
        """True when the underlying fastcs attribute is read/write.

        >>> NewPv.same("X:Y").writable
        False
        >>> NewPv(read="X:Y_RBV", write="X:Y").writable
        True
        """
        return self.read != self.write


#: Full legacy PV (prefix *and* record suffix) -> its replacement.
SubstitutionMap = dict[str, NewPv]


def link_is_reading(attribute: str, flags: str) -> bool | None:
    """Whether a link reads from, or writes to, the PV it names.

    The rules are tried in order and the first that fires wins:

    1. the trailing link flags contain ``CP``, ``CPP``, ``MS``, ``MSS`` or
       ``MSI`` -- reading;
    2. else the flags contain ``PP`` or ``NPP`` -- writing;
    3. else the attribute name looks like an output link -- writing;
    4. else the attribute name looks like an input link -- reading;
    5. else undecidable.

    :param attribute: the builder attribute the value came from, e.g. ``INP1``.
    :param flags: the non-whitespace tokens following the PV in the same value.
    :returns: True for reading, False for writing, None when nothing decided it
        -- the caller then defaults to reading and, for a writable leaf, emits
        ``link-direction-guess``.

    >>> link_is_reading("VAL", "CP MS")
    True
    >>> link_is_reading("VAL", "PP")
    False
    >>> link_is_reading("OUTGB0", "")
    >>> link_is_reading("DOL", "")
    False
    >>> link_is_reading("INP1", "")
    True
    """
    tokens = {token.upper() for token in flags.split()}
    if tokens & READ_FLAGS:
        return True
    if tokens & WRITE_FLAGS:
        return False
    if OUTPUT_ATTR_RE.search(attribute):
        return False
    if INPUT_ATTR_RE.search(attribute):
        return True
    return None


class Substituter:
    """Applies a prepared substitution map to builder entity values."""

    def __init__(
        self,
        subs: SubstitutionMap,
        owners: dict[str, str],
        unresolved: dict[str, tuple[str, str, str | None]],
        known_labels: dict[str, str],
    ) -> None:
        """
        :param subs: full legacy PV -> replacement.
        :param owners: full legacy PV -> the scanner IOC whose chain owns it.
        :param unresolved: full legacy PV -> ``(code, message, chain)`` for PVs
            that were deliberately dropped from *subs* (an ambiguous mapping,
            say). Referencing one raises the recorded diagnostic and leaves the
            token alone.
        :param known_labels: coupler label -> the scanner IOC declaring it. Used
            to tell a bad ``MOD`` number on a known chain (``mod-out-of-range``,
            which fails that chain) from a reference to a label no chain
            declares at all (``unknown-chain-label``, which fails only the
            consumer IOC).
        """
        self.subs = subs
        self.owners = owners
        self.unresolved = unresolved
        self.known_labels = known_labels
        self._references: dict[str, set[str]] = {}
        self._touched: set[str] = set()

    # -- internals ---------------------------------------------------------

    def _note_reference(self, ioc: str, chain: str | None) -> None:
        if chain:
            self._references.setdefault(ioc, set()).add(chain)

    def _diagnose_unknown(
        self,
        token: str,
        *,
        log: DiagnosticLog,
        ioc: str,
        entity: str | None,
        attribute: str,
    ) -> None:
        """Report a token that looks like a legacy PV but resolves to nothing."""
        label, _, remainder = token.partition(":")
        chain = self.known_labels.get(label)
        if chain is not None:
            log.add(
                "mod-out-of-range",
                f"{token} references coupler label {label}, which chain {chain} "
                f"declares, but that chain has no terminal providing {remainder}",
                chain=chain,
                ioc=ioc,
                entity=entity,
                attribute=attribute,
            )
            self._note_reference(ioc, chain)
        else:
            log.add(
                "unknown-chain-label",
                f"{token} references coupler label {label}, "
                "which no converted chain declares",
                chain=None,
                ioc=ioc,
                entity=entity,
                attribute=attribute,
            )

    @staticmethod
    def _trailing_flags(parts: list[str], index: int) -> str:
        """The non-whitespace tokens of *parts* that follow position *index*."""
        return " ".join(
            token for token in parts[index + 1 :] if token and not token.isspace()
        )

    # -- public API --------------------------------------------------------

    def rewrite_value(
        self,
        value: str,
        *,
        attribute: str,
        log: DiagnosticLog,
        ioc: str,
        entity: str | None,
    ) -> str:
        """Rewrite every legacy PV token in *value*, preserving everything else.

        Whitespace runs and trailing EPICS link flags survive verbatim; only
        whole tokens that are exact keys of the substitution map change.
        """
        parts = re.split(r"(\s+)", value)
        changed = False
        for index, token in enumerate(parts):
            if not token or token.isspace():
                continue
            new_pv = self.subs.get(token)
            if new_pv is not None:
                flags = self._trailing_flags(parts, index)
                reading = link_is_reading(attribute, flags)
                if reading is None:
                    reading = True
                    if new_pv.writable:
                        log.add(
                            "link-direction-guess",
                            f"cannot tell whether {token} is read or written "
                            f"by {attribute}; assuming it is read and using "
                            f"{new_pv.read}",
                            chain=self.owners.get(token),
                            ioc=ioc,
                            entity=entity,
                            attribute=attribute,
                        )
                replacement = new_pv.read if reading else new_pv.write
                self._note_reference(ioc, self.owners.get(token))
                if replacement != token:
                    parts[index] = replacement
                    changed = True
                continue

            dropped = self.unresolved.get(token)
            if dropped is not None:
                code, message, chain = dropped
                log.add(
                    code,
                    message,
                    chain=chain,
                    ioc=ioc,
                    entity=entity,
                    attribute=attribute,
                )
                self._note_reference(ioc, chain)
                continue

            if LEGACY_PV_RE.match(token):
                self._diagnose_unknown(
                    token, log=log, ioc=ioc, entity=entity, attribute=attribute
                )

        if not changed:
            return value
        self._touched.add(ioc)
        return "".join(parts)

    def rewrite_entity(
        self, entity: dict[str, Any], *, log: DiagnosticLog, ioc: str
    ) -> bool:
        """Rewrite every string value of a parsed builder entity in place.

        The ``type`` key is never touched. Returns True when anything changed.
        """
        name = entity.get("name")
        entity_name = name if isinstance(name, str) else None
        changed = False
        for key, value in list(entity.items()):
            if key == "type" or not isinstance(value, str):
                continue
            new_value = self.rewrite_value(
                value, attribute=key, log=log, ioc=ioc, entity=entity_name
            )
            if new_value != value:
                entity[key] = new_value
                changed = True
        return changed

    def _known_tokens(
        self, entities: Iterable[dict[str, Any]]
    ) -> dict[str, tuple[str | None, str]]:
        """Legacy PVs *entities* name -> where the first sighting was.

        Only tokens the substitution map actually knows are collected, so this
        never has to guess what is and is not a PV.
        """
        found: dict[str, tuple[str | None, str]] = {}
        for entity in entities:
            name = entity.get("name")
            entity_name = name if isinstance(name, str) else None
            for key, value in entity.items():
                if key == "type" or not isinstance(value, str):
                    continue
                for token in value.split():
                    known = token in self.subs or self.unresolved.get(token) is not None
                    if known:
                        found.setdefault(token, (entity_name, key))
        return found

    def report_dropped(
        self,
        raw_entities: Iterable[dict[str, Any]],
        kept_entities: Iterable[dict[str, Any]],
        *,
        log: DiagnosticLog,
        ioc: str,
    ) -> list[str]:
        """Report legacy PVs that vanished with an entity the converter dropped.

        Some builder elements have no ibek equivalent and are deleted outright
        -- ``records.*`` most of all. A deleted entity cannot be rewritten, so
        an EtherCAT reference inside one leaves no trace in the converted IOC
        and no trace in the report either: the operator is never told that IOC
        had an EtherCAT dependency to re-create by hand. This closes that gap.

        A WARNING, not an error: nothing dangles, because the record itself is
        gone. It is information the human needs, not a reason to stop.

        :param raw_entities: every element of the source XML, before conversion.
        :param kept_entities: the converted entities, taken *before* they were
            rewritten -- afterwards they hold the new names, not the legacy ones.
        :returns: the legacy PVs reported, sorted.
        """
        dropped = self._known_tokens(raw_entities)
        for token in self._known_tokens(kept_entities):
            dropped.pop(token, None)
        for token, (entity, attribute) in sorted(dropped.items()):
            log.add(
                "dropped-reference",
                f"{token} is referenced by an entity that has no ibek equivalent "
                "and was dropped in conversion, so the reference was neither "
                "rewritten nor kept; re-create it by hand if it is still needed",
                chain=self.owners.get(token),
                ioc=ioc,
                entity=entity,
                attribute=attribute,
            )
        return sorted(dropped)

    def references(self, ioc: str) -> set[str]:
        """The scanner IOCs *ioc* depends on, including via failed references."""
        return set(self._references.get(ioc, ()))

    def touched_iocs(self) -> set[str]:
        """The consumer IOCs in which at least one value was actually rewritten."""
        return set(self._touched)
