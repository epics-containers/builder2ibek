# Module Special Cases

Some modules have non-standard naming or locations. **Always consult this list
before creating a support YAML or looking up a module.**

## `epics` — provided by ibek, not a support module

The `epics` entity types (`EpicsEnvSet`, `StartupCommand`,
`PostStartupCommand`, `dbpf`, `EpicsCaMaxArrayBytes`, `InterruptVectorVME`)
are provided by ibek itself. They do **not** live in `ibek-support/` or
`ibek-support-dls/`. Do NOT create an `epics` support YAML.

## `IOCInfo` — case-sensitive naming

The converter and support YAML use the casing **`IOCInfo`** (capital I at the
end), not `IOCinfo`.

Do NOT create a duplicate `IOCinfo/` folder — always use `IOCInfo/`.

## `pmacCoord` — separate from `pmac`

`pmacCoord` has its own support YAML in `ibek-support-dls/pmacCoord/`, distinct
from the `pmac` module in `ibek-support/pmac/`. Do not merge them.

## `devIocStats` — use the public `ibek-support/iocStats`

The public module at `ibek-support/iocStats/` defines
`module: devIocStats` with `iocAdminSoft` using the `$(IOCSTATS)` macro.
Do **not** create a `ibek-support-dls/devIocStats/` — the DLS-specific
copy was removed as redundant.
