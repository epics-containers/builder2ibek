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

The public module at `ibek-support/iocStats/` defines `module: devIocStats`.
Only `iocAdminSoft`, `iocAdminScanMon`, and `iocAdminVxWorks` entities remain
(referencing only upstream-shipped db files). The former `devIocStatsHelper`
and `iocGui` entities were dropped because they referenced `iocGui.db`, a
DLS-only addition not in upstream iocStats.

`convert.py` injects `devIocStats.iocAdminSoft` as a default for every IOC,
and `deviocstats.py` drops any incoming `devIocStats.*` XML entity. Support
module entity models must not add `devIocStats.*` to `sub_entities`.

Do **not** create a `ibek-support-dls/devIocStats/`.

## `ether_ip` — DLS template shipped via ibek-support

`ether_ip_plcInfo.template` is a DLS addition not in upstream
`epics-modules/ether_ip`. It's shipped from
`ibek-support/ether_ip/ether_ip_plcInfo.template` and copied into the built
module's `db/` via a `bash` post_build entry in `ether_ip.install.yml`.
See `ibek-support-ansible` skill for the pattern.
