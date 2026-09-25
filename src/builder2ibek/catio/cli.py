"""The body of the ``builder2ibek catio`` command.

One invocation migrates a whole beamline off the legacy `ethercat` support
module: it discovers every EtherCAT chain in a BUILDER tree, predicts the PV
names fastcs-catio will generate, rewrites every consumer IOC's references to
match, and writes both the rewritten consumer IOCs and one fastcs-catio IOC per
chain into a services repo.

Failure is **per chain**, never all-or-nothing. A chain that records an ERROR
contributes no substitutions and gets no fastcs-catio IOC; any consumer IOC
referencing it is skipped whole, even where its other chains are clean, because
a half-rewritten IOC is worse than an unconverted one. The report names the
chain that blocked each skipped IOC.

Ordering matters and is not arbitrary: *every* candidate IOC is converted before
*any* is written. Reference-time diagnostics -- a MOD number off the end of a
chain, a record with no fastcs equivalent -- are what populate
:meth:`~builder2ibek.catio.diagnostics.DiagnosticLog.failed_chains`, so the
write decision cannot be made until the last IOC has been converted. Converting
has no side effects until :func:`builder2ibek.catio.services.write_ioc` is
called, so the two-pass shape costs nothing.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import typer
from ruamel.yaml import YAML

from builder2ibek.catio.chains import (
    MAKE_IOCS,
    Chain,
    build_substituter,
    discover_chains,
    report_unused_ambiguities,
)
from builder2ibek.catio.diagnostics import DiagnosticLog
from builder2ibek.catio.substitute import Substituter
from builder2ibek.convert import convert_to_ioc
from builder2ibek.converters.ethercat import CatioContext
from builder2ibek.types import Generic_IOC

__all__ = [
    "PLACEHOLDER_RE",
    "CatioReport",
    "apply_prefix_overrides",
    "catio_cli",
]

#: A scaffold value a human must replace before the IOC can be deployed.
PLACEHOLDER_RE = re.compile(r"REPLACE_WITH_[A-Z0-9_]*")

#: Sticky ordinals mean a chain deleted from the BUILDER tree keeps its
#: ``E{n}RIO`` number reserved by its leftover services folder, and nothing
#: reclaims it. Reclaiming would renumber a live chain and repoint every PV a
#: previous run rewrote at a name nothing creates. Open item, plan D11.
ORDINAL_NOTE = (
    "note: chain ordinals are sticky -- a chain removed from the BUILDER tree "
    "keeps its E{n}RIO ordinal reserved by its leftover services folder and "
    "nothing reclaims it (D11, open)"
)


def _load_services() -> Any:
    """Import :mod:`builder2ibek.catio.services` on demand.

    Deferred rather than imported at module scope for the same reason
    :mod:`~builder2ibek.catio.chains` defers `fastcs_catio`: nothing outside the
    ``catio`` command should pay for the services-repo writer, and tests can
    replace this function to drive the whole flow without touching a real repo.
    """
    from builder2ibek.catio import services

    return services


# -- input discovery ---------------------------------------------------------


def _xml_dir(builder_path: Path) -> Path:
    """The directory holding the IOC XMLs, given a BUILDER root or a leaf dir.

    Mirrors :func:`builder2ibek.catio.chains.discover_chains` exactly, so the
    chains and the consumer IOCs are always read from the same place.
    """
    search = builder_path / MAKE_IOCS
    return search if search.is_dir() else builder_path


def _is_template_xml(xml: Path) -> bool:
    """True for a macro template rather than a real IOC definition.

    >>> _is_template_xml(Path("GIGE-FIT-TEMPLATE.xml"))
    True
    >>> _is_template_xml(Path("BL21I-VA-IOC-02.xml"))
    False
    """
    name = xml.name
    return "$(" in name or "template" in name.lower()


def _existing_description(services_repo: Path, ioc_name: str) -> str:
    """The ``description`` of an already-deployed IOC, or ``""``.

    Carried across so that re-running ``catio`` over a converted beamline does
    not replace a curated description with the generic auto-generated one.
    """
    ioc_yaml = services_repo / "services" / ioc_name.lower() / "config" / "ioc.yaml"
    if not ioc_yaml.is_file():
        return ""
    try:
        data = YAML(typ="safe").load(ioc_yaml)
    except Exception:  # noqa: BLE001 - a corrupt file just means no description
        return ""
    if not isinstance(data, dict):
        return ""
    description = data.get("description") or ""
    return "" if str(description).startswith("REPLACE_WITH") else str(description)


# -- name-mapping overrides --------------------------------------------------


def _expand_template(template: str | None, chain: Chain) -> str | None:
    """Substitute ``{domain}`` and ``{n}`` in a CLI-supplied prefix template.

    Plain text replacement, **not** :meth:`str.format`: the templates also carry
    the positional ``{:02d}`` and the named ``{id}`` / ``{group_alias}`` /
    ``{node_prefix}`` that fastcs-catio itself expands later, and ``format``
    would either consume or reject those.

    >>> chain = Chain("BL21I-VA-IOC-01", "BL21I-VA", 3)
    >>> _expand_template("{domain}-E{n}RIO-{:02d}", chain)
    'BL21I-VA-E3RIO-{:02d}'
    >>> _expand_template(None, chain) is None
    True
    """
    if template is None:
        return None
    return template.replace("{domain}", chain.domain).replace("{n}", str(chain.ordinal))


class _OverriddenChain(Chain):
    """A :class:`Chain` whose name-mapping templates come from the CLI.

    A plain subclass rather than extra :class:`Chain` fields: the three
    templates are properties on ``Chain``, and overriding a property is the only
    way to keep ``Chain.name_mappings()`` -- the single source the generated
    ``config/fastcs.yaml`` and the predicted names must both come from -- in
    agreement with the override.

    >>> base = Chain("BL21I-VA-IOC-01", "BL21I-VA", 2)
    >>> chain = _OverriddenChain(base, node_prefix="{domain}-RIO{n}-{:02d}")
    >>> chain.node_prefix, chain.name_mappings()["node_prefix"]
    ('BL21I-VA-RIO2-{:02d}', 'BL21I-VA-RIO2-{:02d}')
    >>> chain.device_prefix == base.device_prefix
    True
    """

    def __init__(
        self,
        chain: Chain,
        *,
        node_prefix: str | None = None,
        module_prefix: str | None = None,
        device_prefix: str | None = None,
    ) -> None:
        super().__init__(
            scanner_ioc=chain.scanner_ioc,
            domain=chain.domain,
            ordinal=chain.ordinal,
            slaves=chain.slaves,
            labels=chain.labels,
        )
        self._node_prefix = _expand_template(node_prefix, chain)
        self._module_prefix = _expand_template(module_prefix, chain)
        self._device_prefix = _expand_template(device_prefix, chain)

    @property
    def node_prefix(self) -> str:
        return self._node_prefix or super().node_prefix

    @property
    def module_prefix(self) -> str:
        return self._module_prefix or super().module_prefix

    @property
    def device_prefix(self) -> str:
        return self._device_prefix or super().device_prefix


def apply_prefix_overrides(
    chains: list[Chain],
    *,
    node_prefix: str | None = None,
    module_prefix: str | None = None,
    device_prefix: str | None = None,
) -> list[Chain]:
    """Re-wrap *chains* so their name mappings use the CLI overrides.

    Returns *chains* unchanged when nothing is overridden, so the common case
    keeps the exact objects :func:`discover_chains` produced.

    >>> chains = [Chain("BL21I-VA-IOC-01", "BL21I-VA", 1)]
    >>> apply_prefix_overrides(chains) is chains
    True
    """
    if node_prefix is None and module_prefix is None and device_prefix is None:
        return chains
    return [
        _OverriddenChain(
            chain,
            node_prefix=node_prefix,
            module_prefix=module_prefix,
            device_prefix=device_prefix,
        )
        for chain in chains
    ]


# -- placeholder reporting ---------------------------------------------------


def _placeholder_line(folder: Path, item: str) -> str:
    """One report line for a placeholder reported by ``services.py``.

    ``write_catio_ioc`` returns the placeholder tokens it left behind; a bare
    token is qualified with the folder it lives in, while anything that already
    carries its own location is passed through untouched.

    >>> _placeholder_line(Path("services/bl21i-va-catio-01"), "REPLACE_WITH_IMAGE")
    'services/bl21i-va-catio-01: REPLACE_WITH_IMAGE'
    >>> _placeholder_line(Path("x"), "values.yaml: REPLACE_WITH_IMAGE")
    'values.yaml: REPLACE_WITH_IMAGE'
    """
    return f"{folder}: {item}" if item.startswith("REPLACE_WITH") else item


def _dedupe_placeholders(lines: Iterable[str]) -> list[str]:
    """Collapse ``location: TOKEN`` lines onto the most specific location.

    ``write_catio_ioc`` reports a placeholder against the IOC *folder* while the
    post-write sweep finds the same token in a named *file* underneath it. Both
    are true, so a plain set keeps both and the report lists every placeholder
    twice. Keep the file, which is the one a human has to open.

    A folder is only collapsed away for the token that was found beneath it, so
    a placeholder unique to the folder itself still survives.

    >>> _dedupe_placeholders(["a: T", "a/values.yaml: T", "b: U"])
    ['a/values.yaml: T', 'b: U']
    >>> _dedupe_placeholders(["a: T", "a/values.yaml: V"])
    ['a/values.yaml: V', 'a: T']
    """
    seen = dict.fromkeys(lines)
    split = [(line, *line.split(": ", 1)) for line in seen if ": " in line]
    specific = {(loc, token) for _, loc, token in split}
    kept = [
        line
        for line, loc, token in split
        if not any(
            other.startswith(f"{loc}/")
            for other, other_token in specific
            if other_token == token
        )
    ]
    return sorted(kept + [line for line in seen if ": " not in line])


def _scan_placeholders(folder: Path) -> list[str]:
    """Every ``REPLACE_WITH_*`` token under *folder*, as ``path: TOKEN`` lines.

    A belt-and-braces sweep of what was actually written, so a placeholder that
    ``services.py`` did not report still reaches the human. Symlinked
    directories are not descended into -- in a services repo ``templates`` is a
    symlink to the shared chart, which is not this IOC's to fill in.
    """
    lines: list[str] = []
    if not folder.is_dir():
        return lines
    stack = [folder]
    while stack:
        current = stack.pop()
        for child in sorted(current.iterdir()):
            if child.is_symlink():
                continue
            if child.is_dir():
                stack.append(child)
                continue
            try:
                text = child.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for token in dict.fromkeys(PLACEHOLDER_RE.findall(text)):
                lines.append(f"{child}: {token}")
    return sorted(lines)


# -- the report --------------------------------------------------------------


@dataclass
class CatioReport:
    """Everything one ``catio`` run did, ready to render or serialise."""

    builder_path: str
    services_repo: str
    strict: bool
    dry_run: bool
    chains: list[dict] = field(default_factory=list)
    iocs_written: list[str] = field(default_factory=list)
    iocs_skipped: list[dict] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    conversion_errors: list[dict] = field(default_factory=list)
    #: consumer IOC -> the services path written, for the human report only.
    ioc_paths: dict[str, str] = field(default_factory=dict)


def _render_report(report: CatioReport, log: DiagnosticLog) -> str:
    """The human report: diagnostics, then what was done, then what is left."""
    converted = [c for c in report.chains if c["converted"]]
    failed = [c for c in report.chains if not c["converted"]]
    lines = [
        log.render(),
        "",
        f"Builder XMLs:      {report.builder_path}",
        f"Services repo:     {report.services_repo}",
        f"Chains discovered: {len(report.chains)}",
        f"Chains converted:  {len(converted)}",
        f"Chains failed:     {len(failed)}",
        f"IOCs written:      {len(report.iocs_written)}",
        f"IOCs skipped:      {len(report.iocs_skipped)}",
    ]
    if report.dry_run:
        lines.append("DRY RUN -- nothing was written")

    if report.chains:
        lines += ["", "Chains:"]
        for chain in report.chains:
            state = "converted" if chain["converted"] else "FAILED (skipped)"
            lines.append(
                f"  {chain['scanner_ioc']} -> {chain['catio_ioc']} "
                f"[{state}] node_prefix {chain['node_prefix']}"
            )

    if report.iocs_written:
        lines += ["", "IOCs written:"]
        for ioc in report.iocs_written:
            path = report.ioc_paths.get(ioc, "")
            lines.append(f"  {ioc}{f' -> {path}' if path else ''}")

    if report.iocs_skipped:
        lines += ["", "IOCs skipped:"]
        for item in report.iocs_skipped:
            blocked = ", ".join(item["blocked_by"]) or "-"
            reason = "own errors; " if item["own_errors"] else ""
            lines.append(f"  {item['ioc']} ({reason}blocked by chain {blocked})")

    if report.conversion_errors:
        lines += ["", "Conversion errors (IOC left untouched):"]
        for item in report.conversion_errors:
            lines.append(f"  {item['ioc']}: {item['error']}")

    lines += ["", "Placeholders to fill in:"]
    if report.placeholders:
        lines += [f"  {line}" for line in report.placeholders]
    else:
        lines.append("  (none)")

    lines += ["", ORDINAL_NOTE]
    return "\n".join(lines)


def _to_json(report: CatioReport, log: DiagnosticLog) -> str:
    data = asdict(report)
    data["diagnostics"] = log.to_json()
    return json.dumps(data, indent=2)


# -- the command -------------------------------------------------------------


def _convert_all(
    xml_dir: Path,
    services_repo: Path,
    substituter: Substituter,
    log: DiagnosticLog,
    report: CatioReport,
) -> dict[str, Generic_IOC]:
    """Convert every candidate IOC XML, rewriting its EtherCAT references.

    Every XML is converted, because whether an IOC references a chain is only
    known once its values have been walked. Nothing is written here.

    A conversion that raises is recorded and that IOC is dropped from the run.
    Only a *scanner* failing this way is fatal: an unrelated converter defect in
    some other IOC is `/beamline-convert`'s problem, not this command's, and
    must not block the whole beamline's EtherCAT migration.
    """
    converted: dict[str, Generic_IOC] = {}
    for xml in sorted(xml_dir.glob("*.xml")):
        if _is_template_xml(xml):
            continue
        ioc_name = xml.stem
        try:
            converted[ioc_name] = convert_to_ioc(
                xml,
                description=_existing_description(services_repo, ioc_name),
                catio=CatioContext(substituter=substituter, log=log, ioc_name=ioc_name),
            )
        except Exception as exc:  # noqa: BLE001 - report any converter failure
            report.conversion_errors.append(
                {"ioc": ioc_name, "error": f"{type(exc).__name__}: {exc}"}
            )
    return converted


def _fail(message: str, *, json_out: bool) -> NoReturn:
    """Report a run that could not start at all, and exit non-zero."""
    if json_out:
        print(json.dumps({"error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    raise typer.Exit(1)


def catio_cli(
    builder_path: Path,
    services_repo: Path,
    *,
    strict: bool = False,
    dry_run: bool = False,
    json_out: bool = False,
    node_prefix: str | None = None,
    module_prefix: str | None = None,
    device_prefix: str | None = None,
) -> None:
    """Run the whole migration and print the report.

    :raises typer.Exit: with code 1 when any ERROR was recorded, a scanner IOC
        failed to convert, or the run could not start at all.
    """
    services = _load_services()

    try:
        if not builder_path.is_dir():
            raise FileNotFoundError(f"builder path not found: {builder_path}")
        if not services_repo.is_dir():
            raise FileNotFoundError(f"services repo not found: {services_repo}")

        sticky = services.read_sticky_ordinals(services_repo)
        log = DiagnosticLog(strict=strict)
        chains = discover_chains(builder_path, log, sticky=sticky)
        chains = apply_prefix_overrides(
            chains,
            node_prefix=node_prefix,
            module_prefix=module_prefix,
            device_prefix=device_prefix,
        )
        substituter = build_substituter(chains, log)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        _fail(f"{type(exc).__name__}: {exc}", json_out=json_out)

    # Converter chatter must not pollute a `--json` stdout, and is noise in the
    # human report too.
    with contextlib.redirect_stdout(sys.stderr):
        report = CatioReport(
            builder_path=str(builder_path),
            services_repo=str(services_repo),
            strict=strict,
            dry_run=dry_run,
        )
        xml_dir = _xml_dir(builder_path)
        iocs = _convert_all(xml_dir, services_repo, substituter, log, report)

        scanners = {chain.scanner_ioc for chain in chains}
        failed_chains = log.failed_chains()
        failed_iocs = log.failed_iocs()

        for ioc_name, ioc in iocs.items():
            references = substituter.references(ioc_name)
            own_errors = ioc_name in failed_iocs
            if ioc_name in scanners:
                # A scanner's own chain counts as a reference even when its
                # entities name no PV from it: writing the scanner with its
                # EtherCAT entities stripped, while its replacement catio IOC
                # was skipped, would leave the beamline without that hardware.
                references = references | {ioc_name}
            elif not references and not own_errors:
                # No EtherCAT references at all -- not this command's business.
                continue
            # An IOC whose every reference was to a skipped chain has no
            # *resolved* references at all, only errors of its own; it must
            # still be reported rather than silently passed over.
            blocked = sorted(references & failed_chains)
            if blocked or own_errors:
                report.iocs_skipped.append(
                    {
                        "ioc": ioc_name,
                        "blocked_by": blocked,
                        "own_errors": own_errors,
                    }
                )
                continue
            path = services.write_ioc(services_repo, ioc_name, ioc, dry_run=dry_run)
            report.iocs_written.append(ioc_name)
            report.ioc_paths[ioc_name] = str(path)

        placeholders: list[str] = []
        for chain in chains:
            folder = services_repo / "services" / chain.services_folder
            converted = chain.scanner_ioc not in failed_chains
            report.chains.append(
                {
                    "scanner_ioc": chain.scanner_ioc,
                    "catio_ioc": chain.catio_ioc,
                    "services_folder": chain.services_folder,
                    "domain": chain.domain,
                    "ordinal": chain.ordinal,
                    "slaves": len(chain.slaves),
                    "converted": converted,
                    "path": str(folder),
                    **chain.name_mappings(),
                }
            )
            if not converted:
                continue
            for item in services.write_catio_ioc(services_repo, chain, dry_run=dry_run):
                placeholders.append(_placeholder_line(folder, item))

        if not dry_run:
            folders = [c["services_folder"] for c in report.chains if c["converted"]]
            folders += [name.lower() for name in report.iocs_written]
            for folder_name in folders:
                placeholders += _scan_placeholders(
                    services_repo / "services" / folder_name
                )
        report.placeholders = _dedupe_placeholders(placeholders)

        report_unused_ambiguities(substituter, log)

        scanner_failures = [
            item for item in report.conversion_errors if item["ioc"] in scanners
        ]

    print(_to_json(report, log) if json_out else _render_report(report, log))

    if log.has_errors() or scanner_failures:
        raise typer.Exit(1)
