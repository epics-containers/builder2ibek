"""Structured diagnostics for the `catio` conversion.

A chain-by-chain migration cannot be all-or-nothing: one malformed EtherCAT
chain must not block the other three on the same beamline. Every problem the
converter finds is therefore recorded as a :class:`Diagnostic` carrying enough
location to act on it -- the scanner IOC that owns the affected chain, the
consumer IOC the reference was found in, and the builder entity and attribute
that held it.

Severity drives control flow, not just presentation:

* ``ERROR`` -- the owning chain is skipped: no substitutions come from it and no
  fastcs-catio IOC is written. Any consumer IOC referencing that chain is
  skipped whole, even if its other chains are clean.
* ``WARNING`` -- reported, conversion proceeds.

Codes are a closed set (:data:`CODES`). Passing an unlisted code to
:meth:`DiagnosticLog.add` raises :class:`KeyError` rather than inventing a
severity, so a typo cannot silently downgrade an error to nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    """How badly a diagnostic hurts.

    >>> Severity.ERROR < Severity.WARNING  # errors sort first
    True
    >>> str(Severity.WARNING)
    'warning'
    """

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    """One problem found while converting a chain or a consumer IOC.

    :param code: canonical code, a key of :data:`CODES`.
    :param severity: the severity actually recorded, after any ``--strict``
        promotion -- not necessarily ``CODES[code]``.
    :param message: human-readable detail, no location (the location fields
        supply that).
    :param chain: scanner IOC name owning the affected chain, e.g.
        ``"BL21I-VA-IOC-01"``. `None` for problems not tied to a chain.
    :param ioc: the consumer IOC the diagnostic was raised from.
    :param entity: builder entity name within *ioc*.
    :param attribute: builder attribute (argument) name within *entity*.
    """

    code: str
    severity: Severity
    message: str
    chain: str | None = None
    ioc: str | None = None
    entity: str | None = None
    attribute: str | None = None

    def location(self) -> str:
        """The location prefix used by :meth:`__str__`, possibly empty.

        The consumer IOC is preferred over the chain because that is where a
        human must go to fix a bad reference; the chain is only shown when no
        consumer is known.

        >>> Diagnostic("unmapped-suffix", Severity.ERROR, "x",
        ...            ioc="BL21I-VA-IOC-05", entity="VAFAN4",
        ...            attribute="rio_dinput").location()
        'BL21I-VA-IOC-05, entity VAFAN4, arg rio_dinput'
        >>> Diagnostic("unlabelled-coupler", Severity.WARNING, "x",
        ...            chain="BL21I-DI-IOC-01").location()
        'chain BL21I-DI-IOC-01'
        """
        parts: list[str] = []
        if self.ioc:
            parts.append(self.ioc)
        elif self.chain:
            parts.append(f"chain {self.chain}")
        if self.entity:
            parts.append(f"entity {self.entity}")
        if self.attribute:
            parts.append(f"arg {self.attribute}")
        return ", ".join(parts)

    def __str__(self) -> str:
        """One-line report form naming severity, code, location and message.

        >>> print(Diagnostic("mod-out-of-range", Severity.ERROR,
        ...                  "MOD9 exceeds 8 terminals",
        ...                  chain="BL21I-VA-IOC-01", ioc="BL21I-VA-IOC-01",
        ...                  entity="VAFAN4", attribute="rio_dinput"))
        error [mod-out-of-range] BL21I-VA-IOC-01, entity VAFAN4, arg rio_dinput: MOD9 exceeds 8 terminals
        >>> print(Diagnostic("unknown-chain-label", Severity.ERROR, "no such label"))
        error [unknown-chain-label]: no such label
        """  # noqa: E501
        where = self.location()
        head = f"{self.severity} [{self.code}]"
        return f"{head} {where}: {self.message}" if where else f"{head}: {self.message}"

    def to_dict(self) -> dict[str, str | None]:
        """This diagnostic as a plain JSON-serialisable dict.

        >>> Diagnostic("unlabelled-coupler", Severity.WARNING, "no DEVICE",
        ...            chain="BL21I-DI-IOC-01").to_dict()["severity"]
        'warning'
        """
        return {
            "code": self.code,
            "severity": str(self.severity),
            "message": self.message,
            "chain": self.chain,
            "ioc": self.ioc,
            "entity": self.entity,
            "attribute": self.attribute,
        }


#: Canonical diagnostic code -> its default severity.
CODES: dict[str, Severity] = {
    # -- errors: the owning chain cannot be converted --------------------------
    "mod-out-of-range": Severity.ERROR,
    "leaf-type-mismatch": Severity.ERROR,
    "coupler-label-conflict": Severity.ERROR,
    "unknown-chain-label": Severity.ERROR,
    "unknown-terminal-type": Severity.ERROR,
    "unknown-entity-type": Severity.ERROR,
    "unmapped-suffix": Severity.ERROR,
    "ambiguous-legacy-pv": Severity.ERROR,
    "shortened-leaf": Severity.ERROR,
    # -- warnings: reported, conversion proceeds -------------------------------
    "duplicate-coupler-label": Severity.WARNING,
    "ambiguous-legacy-pv-unused": Severity.WARNING,
    "device-mod-mismatch": Severity.WARNING,
    "unlabelled-coupler": Severity.WARNING,
    "device-without-mod": Severity.WARNING,
    "slave-type-mismatch": Severity.WARNING,
    "link-direction-guess": Severity.WARNING,
    "dropped-reference": Severity.WARNING,
}

#: Codes that ``--strict`` promotes from WARNING to ERROR.
STRICT_PROMOTIONS: frozenset[str] = frozenset({"device-mod-mismatch"})

#: Group heading shown for diagnostics with no owning chain.
_NO_CHAIN = "(no chain)"


def _sort_key(diagnostic: Diagnostic) -> tuple[str, ...]:
    """Total order within a render group, independent of insertion order."""
    return (
        diagnostic.code,
        diagnostic.ioc or "",
        diagnostic.entity or "",
        diagnostic.attribute or "",
        diagnostic.message,
    )


class DiagnosticLog:
    """An ordered, queryable collection of :class:`Diagnostic`.

    >>> log = DiagnosticLog()
    >>> _ = log.add("unlabelled-coupler", "no DEVICE with :MOD",
    ...             chain="BL21I-DI-IOC-01")
    >>> _ = log.add("unmapped-suffix", "AL_STATE has no fastcs equivalent",
    ...             chain="BL21I-VA-IOC-01", ioc="BL21I-VA-IOC-05")
    >>> len(log), log.has_errors()
    (2, True)
    >>> sorted(log.failed_chains()), sorted(log.failed_iocs())
    (['BL21I-VA-IOC-01'], ['BL21I-VA-IOC-05'])
    """

    def __init__(self, strict: bool = False) -> None:
        """Create an empty log.

        :param strict: when True, codes in :data:`STRICT_PROMOTIONS` are
            recorded at ``ERROR`` instead of their default severity.
        """
        self.strict = strict
        self._diagnostics: list[Diagnostic] = []

    def add(
        self,
        code: str,
        message: str,
        *,
        chain: str | None = None,
        ioc: str | None = None,
        entity: str | None = None,
        attribute: str | None = None,
    ) -> Diagnostic:
        """Record a diagnostic and return it.

        :param code: must be a key of :data:`CODES`.
        :param message: detail, without location.
        :param chain: scanner IOC owning the affected chain.
        :param ioc: consumer IOC the diagnostic was raised from.
        :param entity: builder entity name.
        :param attribute: builder attribute name.
        :returns: the stored :class:`Diagnostic`.
        :raises KeyError: if *code* is not a known code -- a typo must not
            silently produce an unclassified, and therefore ignored, problem.

        >>> log = DiagnosticLog(strict=True)
        >>> log.add("device-mod-mismatch", "MOD3 but position 4").severity
        <Severity.ERROR: 'error'>
        >>> DiagnosticLog().add("nonsuch", "boom")
        Traceback (most recent call last):
            ...
        KeyError: "unknown diagnostic code 'nonsuch'"
        """
        try:
            severity = CODES[code]
        except KeyError:
            raise KeyError(f"unknown diagnostic code {code!r}") from None
        if self.strict and code in STRICT_PROMOTIONS:
            severity = Severity.ERROR
        diagnostic = Diagnostic(
            code=code,
            severity=severity,
            message=message,
            chain=chain,
            ioc=ioc,
            entity=entity,
            attribute=attribute,
        )
        self._diagnostics.append(diagnostic)
        return diagnostic

    def __iter__(self) -> Iterator[Diagnostic]:
        """Iterate the diagnostics in the order they were added."""
        return iter(self._diagnostics)

    def __len__(self) -> int:
        """The number of diagnostics recorded."""
        return len(self._diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        """Every diagnostic recorded at ``ERROR``, in insertion order."""
        return [d for d in self._diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Every diagnostic recorded at ``WARNING``, in insertion order."""
        return [d for d in self._diagnostics if d.severity is Severity.WARNING]

    def has_errors(self) -> bool:
        """True when at least one ``ERROR`` was recorded.

        >>> log = DiagnosticLog()
        >>> log.has_errors()
        False
        >>> _ = log.add("device-without-mod", "no :MOD in DEVICE")
        >>> log.has_errors()
        False
        """
        return any(d.severity is Severity.ERROR for d in self._diagnostics)

    def failed_chains(self) -> set[str]:
        """Scanner IOCs whose chain hit at least one error.

        Such a chain is skipped entirely: no substitutions and no
        fastcs-catio IOC.
        """
        return {d.chain for d in self.errors if d.chain}

    def failed_iocs(self) -> set[str]:
        """Consumer IOCs that hit at least one error of their own.

        This is *not* the full skip list -- an IOC referencing a chain in
        :meth:`failed_chains` is skipped too, even with a clean record here.
        """
        return {d.ioc for d in self.errors if d.ioc}

    def render(self) -> str:
        """A human report: errors first, then warnings, grouped by chain.

        Ordering is fully sorted rather than insertion-ordered, so two runs
        over the same beamline produce byte-identical reports.

        :returns: the report, ending in a ``N errors, M warnings`` summary.

        >>> log = DiagnosticLog()
        >>> _ = log.add("device-without-mod", "BL21I-OP-LED-01 has no :MOD",
        ...             chain="BL21I-VA-IOC-06")
        >>> _ = log.add("unmapped-suffix", "AL_STATE has no fastcs equivalent",
        ...             chain="BL21I-VA-IOC-01", ioc="BL21I-VA-IOC-05",
        ...             entity="vacFan", attribute="rio_dinput")
        >>> print(log.render())
        ERRORS
          chain BL21I-VA-IOC-01
            error [unmapped-suffix] BL21I-VA-IOC-05, entity vacFan, arg rio_dinput: AL_STATE has no fastcs equivalent
        <BLANKLINE>
        WARNINGS
          chain BL21I-VA-IOC-06
            warning [device-without-mod] chain BL21I-VA-IOC-06: BL21I-OP-LED-01 has no :MOD
        <BLANKLINE>
        1 errors, 1 warnings
        """  # noqa: E501
        blocks: list[str] = []
        for heading, group in (("ERRORS", self.errors), ("WARNINGS", self.warnings)):
            if not group:
                continue
            lines = [heading]
            by_chain: dict[str, list[Diagnostic]] = {}
            for diag in group:
                by_chain.setdefault(diag.chain or _NO_CHAIN, []).append(diag)
            for chain in sorted(by_chain, key=lambda c: (c == _NO_CHAIN, c)):
                lines.append(
                    f"  {_NO_CHAIN}" if chain == _NO_CHAIN else f"  chain {chain}"
                )
                lines += [f"    {d}" for d in sorted(by_chain[chain], key=_sort_key)]
            blocks.append("\n".join(lines))
        blocks.append(f"{len(self.errors)} errors, {len(self.warnings)} warnings")
        return "\n\n".join(blocks)

    def to_json(self) -> list[dict]:
        """Every diagnostic as plain dicts, ready for :func:`json.dumps`.

        Insertion order is preserved so a machine consumer can reconstruct the
        sequence of events.

        >>> log = DiagnosticLog()
        >>> _ = log.add("link-direction-guess", "assumed read", ioc="BL21I-DI-IOC-02")
        >>> log.to_json()
        [{'code': 'link-direction-guess', 'severity': 'warning', 'message': 'assumed read', 'chain': None, 'ioc': 'BL21I-DI-IOC-02', 'entity': None, 'attribute': None}]
        """  # noqa: E501
        return [d.to_dict() for d in self._diagnostics]
