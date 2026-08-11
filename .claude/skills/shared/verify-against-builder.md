# Verifying a conversion against XMLbuilder's own output

The built IOC that XMLbuilder produced is the system of record. Compare against
**that**, not against a previous conversion — a whole class of defect changes no
diff at all and is invisible to any before/after review.

```
<module>-BUILDER/<version>/iocs/<IOC>/<IOC>App/Db/<IOC>_expanded.substitutions
```

## Why a diff-based review is not enough

Two real examples, both found this way and neither visible in a diff:

- **`vacuumSpace` passed builder short-names into db macros.** Generated
  `{ "SPACE-01:PIRGG", "PIRG1", "PIRG2" }` where builder emits
  `{ "SPACE-01:PIRGG", "BL21I-VA-PIRG-01", "BL21I-VA-PIRG-02" }`. Every gauge,
  img and pirg link in every vacuum space group pointed at a PV that can never
  connect. It had been that way for every converted vacuum IOC.
- **`vacuumSpace.spaceGroup` emits nothing at all** — parameters but no
  `databases` block. Builder emits 6 rows for a super-space; we emit 0. Nothing
  to diff, so nothing to notice (builder2ibek#133).

## The check

Both files are substitutions, but the layouts differ — builder puts the column
header on the `pattern` line unquoted, ibek puts it on the following line
quoted. A parser that assumes one silently returns zero rows for the other,
which reads like a clean result. Handle both, and sanity-check the row count
before drawing any conclusion.

Useful comparisons, in rough order of value:

1. **Per-template instance counts.** Every template XMLbuilder instantiates
   should appear with the same row count. Differences are either a real gap or a
   known design difference (see below).
2. **Device-reference values.** Collect every value in `gauge*`/`img*`/`pirg*`/
   `ionp*`/`valve*`-style columns from both and compare as sets. *Every*
   reference the conversion emits should appear somewhere in builder's output.
   A value that does not is almost always an unresolved short-name.
3. **`st.cmd` command-for-command**, against the boot script — see
   [find-boot-script.md](find-boot-script.md) and
   [vxworks-to-rtems-differences.md](vxworks-to-rtems-differences.md).

## Expected differences — do not chase these

- **Group templates are always emitted.** `vacuumSpace` instantiates a group per
  space; builder only does so where a space has more than one device of that
  type, pointing straight at the device otherwise. Unused slots default to slot
  1, so the group's worst-of reduces to the single device. Same result, more
  records.
- **`entity_enabled` and `type` columns** appear wherever a support YAML uses
  `.*:` in `databases.args`. Harmless.
- `dlssrfile`/`dlssrstatus`/`iocGui` → `save_restoreStatus.db`, and the autosave
  level 1/2 collapse — see [autosave-conversion.md](autosave-conversion.md).

## While you are here: check the module version pin

`ibek-support*/<module>/<module>.install.yml` pins a version that is easy to
leave behind, and a stale pin fails silently — the template still exists, so
generation succeeds and the PVs are simply wrong.

Compare it against the version in the IOC's `_RELEASE`
([find-module-path.md](find-module-path.md)):

```bash
grep "^version:" ibek-support*/<module>/<module>.install.yml
grep -i "^<MODULE>" <path-to>/<IOC>_RELEASE
```

`BL21I` was pinned at `3-4-3` while every I15 `_RELEASE` used `3-11`. In 3-4-3
the SCM10 PV is `:TEMP`; in 3-11 it is `:TEMP_RBV` plus four more records, and
the template had been renamed. Generation was green throughout. A second module
in that support YAML referenced a template that does not exist in 3-4-3 at all.

If the versions differ, diff the templates before bumping — other entity models
in the same support YAML may depend on the older macro set.
