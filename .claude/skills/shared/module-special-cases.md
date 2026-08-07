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

## `autosave` — already converted; never add DLS `dlssr*` entities

`autosave` needs **no new entity models**. The converter at
`src/builder2ibek/converters/autosave.py` already maps
`<autosave.Autosave iocName=.../>` to ibek `autosave.Autosave`, which loads
upstream `save_restoreStatus.db`. It also deletes redundant
`auto_save_restoreStatus` entities.

Do **not** create `dlssrstatus` / `dlssrfile` entity models from the DLS
`autosave` builder.py. They come from `_AutosaveFile` / `_AutosaveStatus`,
which are private (absent from `__all__`) and instantiated inside
`Autosave.__init__`, so no IOC XML can reference them. Their records are
superseded one-for-one by `save_restoreStatus.db` (`$(device):SRSTATUS` →
`$(P)SR_status`, and so on). See
[builder-py-analysis.md](builder-py-analysis.md) Step 2 for the general rule.

## `positioner.motorpositioner` — `motor` is a suffix, not a PV

`motorpositioner.template` resolves the link as `$(P)$(motor).RBV`, and the
motorpositioner takes its `P` from the parent multipositioner (`P: "{{MP.P}}"`).
So `motor` holds the referenced motor's **`M`** (or **`Q`** for
`softMotorForPiezo`) — a bare suffix like `:Y`, which looks wrong but is what
XMLbuilder emitted.

Setting `motor` to `P + M` duplicates the prefix and produces a dead link:
`BL04I-MO-MAPT-01BL04I-MO-MAPT-01:Y.RBV`.

This only works while the motor and the multipositioner share a prefix, which
XMLbuilder asserted and `converters/positioner.py` now checks. If you see
`motor ... prefix does not match multipositioner ... prefix`, the XML is
referencing a motor on another device, and `$(P)$(motor)` cannot express it.
