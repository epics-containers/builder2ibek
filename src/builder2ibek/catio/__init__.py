"""Migration of DLS EtherCAT IOCs from the legacy `ethercat` support module onto
`fastcs-catio`.

fastcs-catio auto-generates its PV names from the bus topology, so they differ
from the ones the legacy `ethercat` templates created. This package predicts the
new names *statically* -- before any hardware is reconfigured -- and rewrites
every consumer IOC's PV references to match.

The modules split by responsibility:

* :mod:`~builder2ibek.catio.leaves` -- legacy record suffix to fastcs attribute
  name, per builder entity type. Pure tables.
* :mod:`~builder2ibek.catio.diagnostics` -- severity-carrying problem reports.
  ``ERROR`` skips the owning chain; ``WARNING`` is reported and conversion
  proceeds.
* :mod:`~builder2ibek.catio.substitute` -- token-wise rewriting of parsed
  builder entity values, including the read/write link-direction rule.
* :mod:`~builder2ibek.catio.chains` -- builder XML to chain topology, PV-name
  prediction, and the substitution map that ties the three together.
* :mod:`~builder2ibek.catio.services` -- services-repo scaffolding: the
  fastcs-catio IOC folder per chain and the rewritten consumer IOCs.
* :mod:`~builder2ibek.catio.cli` -- the ``builder2ibek catio`` command body and
  its report. Not re-exported here, so that importing this package does not drag
  in typer and the converter machinery; ``builder2ibek.__main__`` imports it
  directly.

Only :mod:`~builder2ibek.catio.chains` touches `fastcs_catio`, and it imports it
lazily inside :func:`~builder2ibek.catio.chains.predict_prefixes`: pytest
collects `src` with ``--doctest-modules``, so a top-level import would fail the
whole suite in builder2ibek's own environment, which deliberately does not have
it installed.
"""

from builder2ibek.catio.chains import (
    Chain,
    Slave,
    UnresolvedMap,
    build_substituter,
    catio_ioc_name,
    discover_chains,
    is_scanner,
    parse_chain,
    predict_prefixes,
    report_unused_ambiguities,
)
from builder2ibek.catio.diagnostics import (
    CODES,
    STRICT_PROMOTIONS,
    Diagnostic,
    DiagnosticLog,
    Severity,
)
from builder2ibek.catio.leaves import (
    KNOWN_ENTITY_TYPES,
    TERMINALS,
    Leaf,
    leaf_translations,
    pv_leaf,
    snake_to_pascal,
    unmapped_suffixes,
)
from builder2ibek.catio.services import (
    IBEK_PLACEHOLDERS,
    is_legacy,
    read_sticky_ordinals,
    scaffold,
    write_catio_ioc,
    write_ioc,
)
from builder2ibek.catio.substitute import (
    NewPv,
    Substituter,
    SubstitutionMap,
    link_is_reading,
)

__all__ = [
    "CODES",
    "IBEK_PLACEHOLDERS",
    "KNOWN_ENTITY_TYPES",
    "STRICT_PROMOTIONS",
    "TERMINALS",
    "Chain",
    "Diagnostic",
    "DiagnosticLog",
    "Leaf",
    "NewPv",
    "Severity",
    "Slave",
    "SubstitutionMap",
    "Substituter",
    "UnresolvedMap",
    "build_substituter",
    "catio_ioc_name",
    "discover_chains",
    "is_legacy",
    "is_scanner",
    "leaf_translations",
    "link_is_reading",
    "parse_chain",
    "predict_prefixes",
    "pv_leaf",
    "read_sticky_ordinals",
    "report_unused_ambiguities",
    "scaffold",
    "snake_to_pascal",
    "unmapped_suffixes",
    "write_catio_ioc",
    "write_ioc",
]
