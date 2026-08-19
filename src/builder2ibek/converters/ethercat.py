"""
Convertor for the legacy ``ethercat`` support module.

Legacy ethercat entities have no ibek equivalent: the replacement is
fastcs-catio, which is a separate IOC entirely (see ``builder2ibek catio``).
So every ethercat entity is dropped and a single TODO placeholder is left
behind in place of the ``EthercatMaster``.

When the conversion is driven by the ``catio`` command the IOC additionally
carries a :class:`CatioContext` in ``ioc.catio``; :func:`finalize` then rewrites
every legacy EtherCAT PV reference in the whole IOC to its fastcs-catio name,
and drops the TODO placeholder -- that switch has just been made.
"""

from dataclasses import dataclass, field
from typing import Any

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ethercat"

#: What an ``EthercatMaster`` becomes in a plain ``xml2yaml`` conversion.
TODO_COMMAND = (
    "# TODO: ethercat support requires major rewrite for "
    "epics-containers — switch to fastcs-catio"
)


@dataclass
class CatioContext:
    """
    The per-IOC context a ``builder2ibek catio`` run attaches to ``ioc.catio``.

    Typed loosely on purpose: importing ``builder2ibek.catio`` at module scope
    would make every converter import it, and pytest imports every module under
    ``src`` for ``--doctest-modules``.

    ``substituter`` is a ``builder2ibek.catio.substitute.Substituter``,
    ``log`` a ``builder2ibek.catio.diagnostics.DiagnosticLog``.

    ``raw_entities`` is filled in by ``builder2ibek.convert.dispatch`` with
    every element of the source XML, so :func:`finalize` can tell which
    references were lost with an entity the conversion dropped.
    """

    substituter: Any
    log: Any
    ioc_name: str
    raw_entities: list[dict[str, Any]] = field(default_factory=list)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the ethercat support module.

    Ethercat entities are marked for major rewrite — the new approach uses
    fastcs-catio instead of the legacy ethercat support module.
    """
    if entity_type == "EthercatMaster":
        # Replace the first EthercatMaster with a placeholder comment
        entity.clear()
        entity.type = "epics.PostStartupCommand"
        entity["command"] = TODO_COMMAND
    else:
        # Drop all other ethercat entities
        entity.delete_me()


def _is_todo_placeholder(entity: dict[str, Any]) -> bool:
    """True for the placeholder :func:`handler` leaves behind for a master."""
    return (
        entity.get("type") == "epics.PostStartupCommand"
        and entity.get("command") == TODO_COMMAND
    )


def finalize(ioc: Generic_IOC) -> None:
    """Apply the catio PV substitutions, if this conversion is a catio run.

    A plain ``xml2yaml`` conversion never sets ``ioc.catio``, so this is a
    no-op there:

    >>> from pathlib import Path
    >>> from builder2ibek.types import Generic_IOC
    >>> ioc = Generic_IOC(
    ...     ioc_name="x", description="", entities=[], source_file=Path("x.xml")
    ... )
    >>> finalize(ioc)
    >>> "catio" in ioc.model_dump()
    False
    """
    ctx = getattr(ioc, "catio", None)
    if ctx is None:
        return

    try:
        # The placeholder tells a human to switch to fastcs-catio; in a catio
        # run that has just happened, so leaving it behind would send whoever
        # reads the IOC looking for work already done. Only a *written* IOC
        # matters, and `catio` skips any scanner whose chain failed, so a
        # placeholder that would reach a services repo is always stale.
        ioc.entities[:] = [e for e in ioc.entities if not _is_todo_placeholder(e)]
        # Snapshot before rewriting: afterwards these hold the *new* names, and
        # the comparison below needs the legacy ones.
        kept = [dict(entity) for entity in ioc.entities]
        for entity in ioc.entities:
            ctx.substituter.rewrite_entity(entity, log=ctx.log, ioc=ctx.ioc_name)
        # `ethercat.*` entities are dropped by design and their replacement is
        # the generated fastcs-catio IOC, so their DEVICE= is not a reference
        # anyone has to re-create by hand.
        raw = [
            entity
            for entity in ctx.raw_entities
            if not str(entity.get("type", "")).startswith(f"{xml_component}.")
        ]
        ctx.substituter.report_dropped(raw, kept, log=ctx.log, ioc=ctx.ioc_name)
    finally:
        # The field is excluded from model_dump(), so this is not what keeps it
        # out of the YAML -- it just stops a spent context outliving the
        # conversion and being applied twice.
        ioc.catio = None
