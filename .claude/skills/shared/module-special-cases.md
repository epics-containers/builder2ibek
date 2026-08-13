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

## `BL<nn><x>-BUILDER` / `BL<nn><x>` — vendor as a runtime pattern, never build

A beamline module (`BL15I-BUILDER`, `BL21I`, `BL04I`, …) holds templates for one
beamline only. It has no business in a generic IOC image, and a `-BUILDER` repo's
top-level Makefile descends into `etc/` and `iocs/`, so building it tries to build
**every IOC on that beamline**.

**Check for compiled code first.** These are template-only in almost every case,
which is what makes them vendorable:

```bash
B=/dls_sw/prod/R3.14.12.7/support/<MODULE>/<version>
find $B -maxdepth 3 -name src -type d
find $B -maxdepth 4 \( -name "*.c" -o -name "*.cpp" -o -name "*.st" -o -name "*.dbd" \) -not -path "*/O.*"
grep -l 'DTYP' $B/db/*.template          # device support => needs a built module
```

- **No hits → vendor it.** Add a pattern folder to `ibek-runtime-support`
  (`<Module>/<Module>.ibek.support.yaml` + a pristine copy of each `.template`
  needed), then `ibek pattern add ibek-runtime-support:<Module> <instance>`.
  Two things differ from a build-time support YAML:
  - `databases[].file` is a **bare filename** (`BL15I-SumTheDiode.template`), not
    `$(MODULE)/db/…` — `ibek runtime place-files` puts it beside the support YAML.
  - Keep `module:` equal to the XML component name so the `ioc.yaml` entity types
    (`BL15I-BUILDER.auto_BL15I_SumTheDiode`) do not change.

  Do **not** also create `ibek-support-dls/<Module>/`. Vendor only the templates
  an IOC actually needs; add more as other IOCs want them.

- **Any hit → STOP and flag it to the user.** Compiled code (src, dbd, libs) or
  `DTYP` device support cannot be vendored — it needs a real built support module,
  and a beamline-specific one in a generic image is a decision for the user, not a
  default. Say which files forced the call.

Requirements to check when vendoring: the IOC **image** must bake `ibek>=4.6.1`
to load a vendored pattern at boot, and `ibek pattern add` soft-skips schema
generation when `values.yaml` has no published image pinned — expected on a
freshly-created instance, not an error. See
[ibek-pattern-vendoring](../ibek-pattern-vendoring/SKILL.md).

`BL19I`/`BL11I` predate this rule and are still build-time modules in
`ibek-support-dls/` — leave them unless you are converting an IOC that needs them.

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

## `dlsPLC` — huge and DLS-internal; edit surgically, keep the anchors

`ibek-support-dls/dlsPLC/dlsPLC.ibek.support.yaml` is ~6100 lines and 74 entity
models. Treat it as an existing file to patch, never as a file to (re)generate.

Its `shared:` block defines ~20 YAML anchors (`*PQ`, `*tagidx`, `*ilk`, `*gilk`,
`*cilk`, `*con_label`, `*sta_label`, `*timeout`, …) merged into models with
`<<: [ *a, *b ]`. `shared` is a first-class field of ibek's `Support` model, so
this is a supported pattern, not a hack — and it is what keeps the file
readable at that size.

Rules when `/support-create` or `/ioc-convert` touches this module:

- **Never round-trip the file through a YAML loader/dumper.** Any load-and-dump
  expands every alias and reformats 6100 lines into an unreviewable diff. Edit
  by hand with the Edit tool only. (Reading it with a loader to *inspect* is
  fine — just never write the result back.)
- **Add, don't rewrite.** Insert a new entity model next to its closest sibling
  so the diff is one contiguous hunk, and reuse the existing anchors rather
  than inlining their parameters.
- Verify with ibek's own loader, which is YAML 1.2:
  `Support(**YAML(typ='safe').load(open(path)))`. Plain `yaml.safe_load` is
  YAML 1.1 and turns the `On`/`Off` label defaults into booleans, producing a
  wall of bogus validation errors.
- `dlsPLC.overrides.yaml` is **legacy**. It was the input to the retired
  external `builder2ibek.support.py` generator, which used to produce the
  support YAML. Nothing reads it now — `update-schema`, `support_defaults.py`
  and `vendor_support_dls.py` all glob `*/*.ibek.support.yaml` only. It is kept
  for grokking the file's history; do **not** mirror new work into it.
- The module builds from vanilla upstream: its `.vdb` sources are flattened to
  `db/*.template` by `ibek-support/vdct` during the container build, so derive
  macros from the flattened `db/*.template` in `/dls_sw/prod/...`, and reference
  `$(DLSPLC)/db/<name>.template` even where the source is a `.vdb`.

Known pre-existing breakage, left alone deliberately: `PIDControl` (and the
same shape in `DCMHeater`, `motionInterlockPLC`) passes required macros its
templates need — `addr`, `UNITS` — without declaring them as parameters, while
declaring others no template uses. Those models cannot render. Fixing them is
its own task; do not fold it into an unrelated conversion.
