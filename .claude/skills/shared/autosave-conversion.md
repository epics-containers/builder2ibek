# Autosave conversion gotchas (DLS VxWorks → ibek)

Translating DLS autosave to `autosave.Autosave` is *mostly* a clean swap of
`save_restore*` / `set_pass*_restoreFile` lines for one entity. One semantic
detail does **not** survive the naive translation and silently corrupts data.

## Settings must be restored at pass 0 *and* pass 1

DLS autosave levels (the `# % autosave N` template hints) map to restore passes:

| DLS level | Restored at |
|---|---|
| `0` | pass 0 (before `iocInit`) → `autosave_positions` |
| `1` | **pass 0 AND pass 1** → `autosave_settings` |
| `2` | pass 1 only → `autosave_settings` |

`builder2ibek autosave` collapses levels 1 **and** 2 into the single
`autosave_settings` file. If that file is restored at **pass 1 only**, the
pass-0 restore that level-1 PVs require is lost.

This breaks any PV whose record **self-initialises from its restored value at
PINI** — the record reads its own (not-yet-restored) value during `iocInit` and
latches the wrong result before the pass-1 restore arrives.

### Canonical failure: `dlsPLC_temperature` `:HIGH`
- `:HIGH` is an `ai` with `INP = <temp>.HIGH CP` (follows the temperature
  record's `.HIGH` field).
- `:HIGH_INIT` is a `PINI=YES` calcout that copies the autosave-restored `:HIGH`
  into `<temp>.HIGH`.
- Pass-1-only restore → `:HIGH_INIT` runs at `iocInit` *before* `:HIGH` is
  restored → the `CP` link delivers `.HIGH = 0` → `:HIGH` collapses to **0**,
  then autosave saves 0 (warning limit effectively disabled).
- `:HIHI` is a plain `ao` with no input link, so its pass-1 restore sticks (70).
  **HIHI works, HIGH doesn't** — that asymmetry is the fingerprint of this bug.

### Fix (applied in the autosave support YAML)
In `ibek-support/autosave/autosave.ibek.support.yaml` `pre_init`, restore
settings at **both** passes:
```
set_pass0_restoreFile autosave_settings.sav
set_pass1_restoreFile autosave_settings.sav
```
Level-2 ("pass 1 only") PVs also get a harmless pass-0 restore. Trade-off: this
changes restore behaviour for *every* IOC using this autosave support (output
settings PVs are seeded at pass 0), but that matches legacy DLS, so it is
proven-safe rather than novel.

### How to spot it during verification
Compare the IOC's written `.sav` against the legacy `<IOC>_N.sav` (normalise a
trailing `.VAL`). A cluster of mismatches where one alarm-limit family holds
(`:HIHI` = 70) while a sibling collapses to 0 (`:HIGH`) is this bug — **not** a
`migrate-autosave` data problem (the seed data is correct; the IOC drives the
value to 0 itself). See `builder2ibek migrate-autosave` and
[vxworks-to-rtems-differences.md](vxworks-to-rtems-differences.md).
