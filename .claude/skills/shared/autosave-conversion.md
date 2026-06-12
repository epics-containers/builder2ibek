# Autosave conversion gotchas (DLS VxWorks/3.14 → ibek RTEMS/EPICS-7)

Translating DLS autosave to `autosave.Autosave` is *mostly* a clean swap of
`save_restore*` / `set_pass*_restoreFile` lines for one entity. Two things do
**not** survive the naive translation. The data (`migrate-autosave` output) is
almost always fine — these are *record/restore* bugs, not data bugs.

---

## 1. Settings must be restored at pass 0 *and* pass 1

DLS autosave levels (the `# % autosave N` template hints) map to restore passes:

| DLS level | Restored at |
|---|---|
| `0` | pass 0 (before `iocInit`) → `autosave_positions` |
| `1` | **pass 0 AND pass 1** → `autosave_settings` |
| `2` | pass 1 only → `autosave_settings` |

`builder2ibek autosave` collapses levels 1 and 2 into one `autosave_settings`
file, and the support YAML originally restored it at **pass 1 only** — losing
the pass-0 restore that level-1 PVs assume. Fix (already applied in
`ibek-support/autosave/autosave.ibek.support.yaml` `pre_init`):
```
set_pass0_restoreFile autosave_settings.sav
set_pass1_restoreFile autosave_settings.sav
```
This is correct DLS semantics and worth keeping. **But on its own it does NOT
fix the `:HIGH` temperature bug below** — that one is deeper.

---

## 2. An `ai`/`CP` "readback" record cannot be autosave-restored on EPICS 7

This is the real root cause of the `dlsPLC_temperature` `:HIGH` limits coming
up as **0** on RTEMS while `:HIHI` works.

### The record design (identical on 3.14 and 7)
```
record(ai, "<temp>:HIGH")      { field(INP, "<temp>.HIGH CP") }   # mirrors the .HIGH FIELD
record(calcout, "<temp>:HIGH_INIT") {                              # PINI: copy :HIGH -> .HIGH
  field(INPA, "<temp>:HIGH PP")   field(OUT, "<temp>.HIGH PP")  field(PINI, "YES")
}
# autosave hint is on the :HIGH RECORD:  #% autosave 1 VAL
```
`:HIGH` is a *pure readback* of the temperature record's `.HIGH` alarm-limit
**field**. On **EPICS 7 an `ai` re-reads its `INP` on every process**, so:
- `caput <temp>:HIGH 60` reads straight back as **0** (it reprocesses and re-reads `.HIGH`).
- At boot, `HIGH_INIT`'s `<temp>:HIGH PP` reprocesses `:HIGH`, which re-reads
  `.HIGH` (=0) → `:HIGH` collapses to 0 → `HIGH_INIT` writes 0 into `.HIGH`.

So `:HIGH` can never hold an autosaved value, and the `:HIGH`→`HIGH_INIT`→`.HIGH`
self-restore chain is dead on EPICS 7.

### Why it worked on VxWorks/3.14
Same records. On 3.14 the `.HIGH CP` link isn't connected yet at PINI, so when
`HIGH_INIT` reprocesses `:HIGH` the `ai` *keeps* its pass-0-restored value (60)
instead of re-reading 0 — `HIGH_INIT` then propagates 60 to `.HIGH`. Pure
3.14-vs-7 link-evaluation timing; nothing in the conversion changed.

Bisection that proves it: boot the original 3.14 IOC and the RTEMS IOC. **Both**
refuse `caput` to `:HIGH` and **both** accept `caput` to `.HIGH`; only startup
differs (3.14 lands `.HIGH=60`, RTEMS lands `.HIGH=0`).

### The fix: autosave the FIELD, not the readback record
`.HIGH` (the field) holds a value fine on both platforms — so save/restore *it*:
```
# dlsPLC_temperature_settings.req  (note: <record> <field>, dot-field of the temp record)
# from
$(device)$(temp):HIGH VAL      # the :HIGH ai record — futile on EPICS 7
# to
$(device)$(temp) HIGH          # the <temp>.HIGH alarm-limit field — the real limit
```
With `.HIGH` restored directly, `HIGH_INIT`/`:HIGH` become harmless leftovers
(restore lands on `.HIGH`; `:HIGH` mirrors it via `CP`). It's the **req file**
that fixes the live IOC — **no template logic change is required**. Two riders:
1. **Re-seed under the new key.** Existing `.sav` stores `<temp>:HIGH 0`; once
   the req points at `<temp>.HIGH`, autosave won't find the old key, so `caput`
   the `.HIGH` fields to their real values once and let autosave save them (or
   re-seed the `.sav`).
2. **Move the template hint too**, else a future `builder2ibek autosave` regen
   re-emits `:HIGH VAL` and reverts the req: put `#% autosave` on the temp
   record's `.HIGH` field. (Generator durability only — not needed at runtime.)

### General lesson
A readback record that mirrors a field via `CP`/`CPP` is **not autosave-able on
EPICS 7** — restore the underlying field. Fingerprint: a put to the readback PV
reads straight back as the field's value; one alarm-limit sibling holds (`:HIHI`,
a plain `ao`) while the readback one (`:HIGH`) collapses to 0.

---

## Verifying autosave after a migrate (recipe)
- The IOC writes `<file>.savB` (and dated backups); `<file>.sav` is the live
  file it restores from. Compare `.sav`/`.savB` against the legacy
  `<IOC>_N.sav`, normalising a trailing `.VAL` on each line.
- **Seed files must be writable by the IOC's NFS uid** (e.g. `37134`), or the
  IOC restores fine but every save fails with `write_it ... Permission denied`
  (saves land only in `.savB`; `.sav` keeps the root/user-owned seed). `chmod
  666`/`chown` the seed `.sav` files. The mount itself is RW — it's the
  root-owned seed that blocks the rewrite.
See `builder2ibek migrate-autosave` and
[vxworks-to-rtems-differences.md](vxworks-to-rtems-differences.md).
