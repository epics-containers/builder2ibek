# Module Special Cases

Some modules have non-standard naming or locations, and some are deliberately
not converted. **Always consult this list before creating a support YAML or
looking up a module.** A module with no section here still needs the checks in
[new-module-folder.md](new-module-folder.md), and the user's answer, before a
new folder is created for it.

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

## `autosave` — already converted; don't add DLS `dlssr*` entities to `ibek-support`

A hybrid RTEMS IOC is the one case that differs. Its binary and db come from the
DLS `autosave` build, so the `dlssr*` templates are available to it, and with
`autosave.Autosave` it serves `$(P)SR_status` rather than the `$(device):SRSTATUS`
names its VxWorks IOC had. Any client still reading those names sees nothing. If
one needs them, the models belong in `ibek-support-dls` under their own module
name, because upstream `autosave` has no such templates.

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

## `adPython` — deprecated; use ADExternal

adPython is deprecated in favour of ADExternal. b2i won't convert it,
whatever `ibek-support-dls` contains: `converters/adPython.py` leaves every
adPython entity out of the ioc.yaml, and `xml2yaml` and `reconvert` print a
won't-convert warning naming the IOC, the entity type and the reason.
`ibek-support-dls` has no adPython folder. Don't add a support YAML
for it, and don't restore its entities by hand in a converted ioc.yaml. Flag
the IOC to the user as needing ADExternal.
ADExternal has no support YAML yet. Whether an automatic adPython to ADExternal
translation is possible is tracked in
https://github.com/epics-containers/builder2ibek/issues/173.

adPython plugins sit in an areaDetector plugin chain. When another plugin takes
its input from the dropped plugin (its `NDARRAY_PORT` is the adPython `PORT`),
the warning lists those entities, and the ioc.yaml fails validation with
`object <port> not found` until they are rewired or the IOC is ported.

## `ADPandABlocks` — replaced by fastcs-pandablocks

ADPandABlocks is replaced by
[fastcs-pandablocks](https://github.com/PandABlocks/fastcs-PandABlocks), which
introspects the PandA itself: an instance needs only each PandA's PV prefix and
box address. b2i never writes ADPandABlocks entities to an ioc.yaml.
`src/builder2ibek/fastcs_panda.py` splits the PandAs out of the XML before
dispatch, and `xml2yaml` and `reconvert` write fastcs instances instead:

- **Dedicated IOC**: PandAs, the elements that belong to them, and boilerplate
  only (`devIocStats`, `autosave`, `EpicsEnvSet` such as
  `EPICS_CA_MAX_ARRAY_BYTES`, `pvlogging.PvLogging`). The IOC's own service
  folder becomes one fastcs instance, with one controller per PandA, and gets
  no ioc.yaml. Given `services/<ioc>/config/ioc.yaml`, xml2yaml writes
  `services/<ioc>/values.yaml` and `config/controller.yaml` from
  `.fastcs_ioc_template`. It removes the ibek-only files from that folder
  (`config/ioc.yaml`, `ioc.schema.json` at the folder root or in `config/`,
  the pvlogging blacklist, `runtime-lock.yaml` and the pattern files it lists)
  and names any other file it leaves in `config/`. The new `values.yaml`
  carries over the ibek one's `securityContext` and `dataVolume` (`pvc: true`,
  or its `hostPath`); if the ibek one set anything else, it is kept as
  `values.yaml.ibek` (or `.ibek.1`, ... when taken) with a warning. A real
  `Chart.yaml` or `templates/` where the template has a symlink is kept, with
  a warning. Outside a services repo the instance is a folder next to the
  `--yaml` path, and that file is left alone.
- **Mixed IOC**: the ioc.yaml keeps the other devices, and each PandA gets its
  own instance, a sibling folder named from its PV prefix in lowercase
  (`services/bl22i-mo-panda-01`). A PandA whose prefix in lowercase is the
  IOC's own name gets `<prefix>-panda` instead, so the two never share a
  folder. The dropped elements are reported as won't convert, naming those
  instances.

Before writing anything, b2i reads every `services/*/config/controller.yaml`,
in the 0.2.x shape (`controllers[].id` / `address`) or the 0.1.0 one
(`controller.address` / `pv_prefix`). A folder with `config/controller.yaml`
is an instance. A PandA is refused, with a warning, when an instance already
serves its prefix or box, or when its own target folder is an instance serving
different controllers (the warning has a diff; merge by hand). Boxes compare
by short hostname, case-insensitive (`panda-01` matches
`panda-01.diamond.ac.uk`); IP addresses compare whole. For a dedicated IOC
nothing is written, and a warning lists all its PandAs; for a mixed one only
that PandA's instance is skipped. An instance serving exactly the XML's
controllers is kept as it is, hand edits included. A mixed IOC whose own
folder is an instance gets no ioc.yaml, with a warning: it was dedicated and
needs merging by hand.

A target folder that is not an instance and not empty (an ibek IOC other than
a dedicated IOC's own, a hand-made folder) stops the conversion before any
file is written, and so does a symlinked folder, `config/`, `values.yaml` or
`controller.yaml`. xml2yaml prints the error and exits 1.

`dataVolume.hostPath` comes from the IOC's own beamline, not the PandA's
prefix. `reconvert` gives a dedicated IOC status `fastcs`, or `refused`, and
passes the notes through in its JSON and summary.

The elements that belong to a PandA: `ADPandABlocks.ADPandABlocks`,
`ADPandABlocks.MotorSync` (no fastcs equivalent, so it is reported), the
areaDetector plugins fed from a PandA port down the `NDARRAY_PORT` chain
(fastcs-pandablocks does its own data capture), and `dbpf`, `StartupCommand`
and `pvlogging.BlacklistPv` elements that name a PV under a PandA's prefix.

The mapping is `P` → controller `id` (the PV prefix) and `HOST` → `address`.
`R` (always `:DRV:`) was the areaDetector driver's suffix and has no
counterpart. fastcs-pandablocks serves PVA only, and its PV names below the
prefix differ from ADPandABlocks', so GDA, ophyd-async and screens need
updating; xml2yaml warns about any other ioc.yaml entity that still names a
PandA PV. The image tag is the single constant `FASTCS_PANDABLOCKS_IMAGE` in
`fastcs_panda.py`; bumping it means vendoring that release's `schema.json`
into `tests/samples/fastcs-pandablocks/`.

Don't add ADPandABlocks support YAML to `ibek-support`. The `ibek-support-dls`
ADPandABlocks folder is removed in a separate MR.

## `procServControl` — not used in containers

procServControl is deprecated for containers: Kubernetes and argocd-monitor
replace it. b2i won't convert it, whatever `ibek-support-dls` contains:
`converters/procServControl.py` leaves every procServControl entity
(`procServControl`, `procServControlGui`) out of the ioc.yaml, and `xml2yaml`
and `reconvert` print a won't-convert warning naming the IOC, the entity type
and the reason. `ibek-support-dls` has no procServControl folder. Don't add a
support YAML for it, and don't restore its entities by
hand in a converted ioc.yaml.

To drop another module the same way, call `ioc.wont_convert(entity, reason)`
from its converter (`Generic_IOC.wont_convert` in `types.py`).

## `gdaPlugins` — use the `detectorPlugins` runtime pattern

The `detectorPlugins` pattern in `ibek-runtime-support` (entity models
`gdaPlugins` and `detectorPlugins`) replaces a gdaPlugins support module.
`converters/gdaPlugins.py` expands the XML element into `ADCore` entities.
Don't create a gdaPlugins folder in either support repo.

## `OXCryo` — use `ibek-support/oxCryo`

`converters/OXCryo.py` maps the `OXCryo` entities (`OXCS700`, `OXNH700`,
`OXCB700`, `OXCB800`) to `oxCryo.*` in `ibek-support/oxCryo/`. Don't create an
`OXCryo` folder in either support repo.

## `motorSmarAct`, `simHDF5Detector` — in `ibek-support`

Both live in `ibek-support/`, built from their public upstreams. Don't create
them in `ibek-support-dls/`.

## `dlsPLC` — huge and DLS-internal; edit surgically, keep the anchors

dlsPLC is a core DLS support module and stays in `ibek-support-dls` for good.
It defines how IOCs talk to every type of PLC at DLS, using the DLS standards
for register assignment. It isn't secret, and a public copy is fine, but it is of no
use outside DLS, so it doesn't belong in `ibek-support`. When sweeping
ibek-support-dls for upstreams or open-source candidates, classify it as
DLS-only and keep it, even if a public mirror turns up.

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
