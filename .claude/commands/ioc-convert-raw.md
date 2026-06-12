---
argument-hint: <path/to/built-IOC-dir> [<path/to/services-repo>]
description: Convert a raw (non-XMLbuilder) built IOC directory to ibek ioc.yaml by reverse-engineering its startup script + compiled db, then validate by round-trip.
---

# Raw IOC Convert Workflow

Convert the **built IOC directory** `$1` — an IOC that was **never** defined in
XMLbuilder, so there is no `.xml` and no per-module converter to drive — into
ibek `ioc.yaml` in the services repo `$2`, then validate it round-trips against
the original startup script and compiled db.

This differs fundamentally from `/ioc-convert` (which parses XML). Here the
source of truth is the **built artifacts on disk**:

| Source in `$1` | Yields |
|---|---|
| `configure/RELEASE` | module set + versions + **old DLS module names** |
| `*App/Db/*_expanded.substitutions` (when present) | **device entities** — template→type, `pattern` columns→params (best source; may be absent) |
| `iocBoot/ioc*/st*.src` | plumbing — asyn ports, serial/IP setup, driver instantiation, boilerplate |
| `db/*_expanded.db` (compiled) | record macros + **fallback device source** when no substitutions; joined by **port name** |

> **Do not defer to `/ioc-convert` even if a `.xml` reference appears in the
> RELEASE header.** This command exists to handle IOCs with no XML; an existing
> XML is only ever useful as an optional ground-truth cross-check (Phase 5c).

This command reuses `/ioc-convert`'s **back half** (support-YAML subagents,
generate2, fix loop) verbatim — only Phases 1–2 below are new.

---

## Phase 0 — Create isolated EPICS_ROOT (main agent)

```bash
export EPICS_ROOT=$(mktemp -d /tmp/epics-ioc-convert-raw-XXXXXX)
```

All subsequent `ibek` and `./update-schema` commands (and subagent prompts) must
have `EPICS_ROOT` set to this value. This lets multiple conversions run in
parallel without clobbering `/epics/` schema state.

---

## Phase 1 — Inventory the built IOC (main agent)

### 1a. Identify the IOC and resolve the services repo

The directory layout is `.../ioc/<BEAMLINE>/<IOC-PREFIX>/<version>`, e.g.
`/dls_sw/prod/R3.14.12.3/ioc/BL21I/BL21I-DI-IOC-02/3-27`:

- `IOC-PREFIX` = the second-to-last path segment, e.g. `BL21I-DI-IOC-02`.
- `IOC_NAME` = lowercase of that, e.g. `bl21i-di-ioc-02`.

Resolve the services repo following
[services-repo-resolution.md](../skills/shared/services-repo-resolution.md),
using `$2` if provided or the IOC prefix otherwise. Apply the legacy-IOC
(`dev-c7:`) and existing-`config/ioc.yaml` handling exactly as `/ioc-convert`
Phase 1a does:

- If `$INSTANCE_DIR` exists with `dev-c7:` in `values.yaml` → `rm -rf` and
  recreate from `.ioc_template`.
- If it exists with a committed `config/ioc.yaml` → ensure clean git state
  before overwriting.
- If it does not exist → copy `services/.ioc_template/` if present, else
  `mkdir -p $INSTANCE_DIR/config/`.

### 1b. Parse `configure/RELEASE`

Read `$1/configure/RELEASE`. Build a **module path table** of every
`MODULE = $(SUPPORT)/<name>/<version>` line → resolved absolute path. Ignore the
auto-generated header and `SUPPORT`/`EPICS_BASE` lines. These are the **old DLS
module names** and pinned versions — keep both; the version disambiguates which
db/template files to read later.

### 1c. Locate the startup script, substitutions, and compiled db

- Startup script: `$1/iocBoot/ioc<IOC-PREFIX>/st<IOC-PREFIX>.src`. Use the
  `.src` (the actual command sequence), **not** the `.sh` wrapper.
- **Expanded substitutions (use if present):**
  `$1/<IOC-PREFIX>App/Db/<IOC-PREFIX>_expanded.substitutions`. When it exists
  this is the **best device-entity source** — see Track A in Phase 2. It may be
  absent (e.g. a hand-written IOC that loads `.db` files directly); fall back to
  the compiled db in that case.
- Compiled db: read the `dbLoadRecords` lines at the end of the `.src` — they
  point at `db/<IOC-PREFIX>_expanded.db` (and sometimes `db/<IOC-PREFIX>.db`).
  These compiled files in `$1/db/` are the **authoritative source of record
  macros** and the **fallback device source** when no substitutions exist.

> **Substitutions vs the CLAUDE.md `.subst` rule.** CLAUDE.md says "macros come
> from the compiled `.db`, never `.subst`" — that is about choosing
> `databases.args` when *authoring a support YAML*. It does **not** forbid using
> the IOC's own post-msi `_expanded.substitutions` to recover which **entity
> instances** exist and their macro **values**. Those are different tasks; using
> the expanded substitutions here is correct.

### 1d. Derive a terse description

A few words describing what the IOC controls, inferred from the prefix and the
dominant drivers in the st.cmd (e.g. "Aravis diagnostic cameras", "Geobrick
motion"). No full sentences.

---

## Phase 2 — Reconstruct entities (main agent)

This is the heart of the command. Entities come from **two tracks that fuse on
the asyn port name**:

- **Track A — devices** (gauges, pumps, valves, PLC, temperature…): the records
  loaded into the IOC. Recover from the **`_expanded.substitutions`** when
  present (best), else from the **compiled `_expanded.db`**.
- **Track B — plumbing** (asyn ports, serial/IP setup, interpose/FINS init,
  driver instantiation): recover from the **st.cmd `.src`**.

A pure camera/driver IOC may have only Track B; a vacuum/temperature/PLC IOC is
mostly Track A with Track B supplying the ports its devices bind to. Do both,
then join.

### 2a. Build the command index

Across **both** support dirs, extract every entity's `pre_init`/`post_init`
template and the leading function-name token, and note every module's
`databases:` template filename(s):

```bash
grep -rn "pre_init\|post_init\|\.template" ibek-support*/*/*.ibek.support.yaml
```

For each module the IOC uses (from the RELEASE table), read its support YAML so
you have the full `pre_init` Jinja templates, parameter lists, **and which
`.template` each entity loads**. **Always check BOTH `ibek-support/` and
`ibek-support-dls/`** — a module lives in exactly one (no duplicates).

### 2b. Track A — recover device entities

**If `_expanded.substitutions` exists (preferred):** each block maps almost 1:1
to ibek entities:

```
file $(DIGITELMPC)/db/digitelMpcIonp.template
pattern { device, port, unit, pump, size, name, ... }
    { "BL15I-VA-IONP-01", "ty_40_0", "01", "1", "300", "IONP1", ... }   # one entity
    { "BL15I-VA-IONP-02", "ty_40_0", "01", "2", "300", "IONP2", ... }   # one entity
```

For each block:
1. **Template file → entity type.** Find the entity whose `databases:` loads that
   `.template` (from the 2a index). If a module exposes it only as an `auto_*`
   entity, the type is `module.auto_<templatebasename>` (see CLAUDE.md `auto_*`
   rule). If no entity model loads it yet, record the module+template for a
   support-YAML subagent (Phase 3).
2. **`pattern { … }` columns → entity parameter names**, one entity per data row,
   values taken positionally. Drop columns the entity model doesn't declare;
   keep `port` (the join key to Track B).
3. Apply the usual `name` rules ([support-yaml-rules.md](../skills/shared/support-yaml-rules.md)).
   **A missing/empty `name` is acceptable** — `name` is rarely used in the
   epics-containers world and is only needed as a `type: id` when another entity
   cross-references this one. If the substitutions `name` column is empty (the
   id came from an XML object name that a raw IOC does not have), just omit it;
   only synthesise an id if a later entity actually refers to it. Do **not**
   report dropped names as a loss.

**If there is no substitutions file:** recover from the compiled `_expanded.db`
instead — group records by their streamDevice/asyn binding
(`@<proto> <args> <port>` or `@asyn(<port>,…)`) and by record-name prefix (the
device `P`), then map each cluster to its module entity via the `.template` it
came from. This is lossier (macro *names* must come from the module `.template`,
not the records) — flag any cluster you cannot confidently map.

### 2c. Track B — recover plumbing from the st.cmd

Tokenize each non-comment, non-blank line. **The tokenizer must handle more than
`verb(args)`:**

- **Assignment form** `VAR = func(args)` (e.g. `IPAC4 = ipacEXTAddCarrier(...)`)
  — strip the `VAR =`, keep the call; remember `VAR` may be referenced later as
  an arg.
- **Bare assignments / shell-isms** `ASPATH = "..."`, `calloc`, `malloc`,
  `strcpy`, `strcat`, `< file`, `putenv`, `ld`, `tyBackspaceSet` — IOC-shell
  housekeeping; drop unless they carry a value a standard entity needs.
- The `STREAM_PROTOCOL_PATH = calloc(...) … strcat(...)` block is the **global
  protocol path** — drop it entirely (handled by the standard entity in 2d; do
  **not** add per CLAUDE.md).

Then classify the real calls per
[module-rename-map.md](../skills/shared/module-rename-map.md):

1. **Boilerplate** (`cd`, `dbLoadDatabase`, `*_registerRecordDeviceDriver`,
   `iocInit`, `save_restore*`, `set_*restoreFile`, `directoryWait`,
   `epicsEnvSet`) → standard entities or drop.
2. **Driver/config calls** → match the verb to a `module.entity`:
   - **Direct match** in exactly one entity's `pre_init`/`post_init`. Use it.
   - **On a miss** the verb was renamed — consult the verb-rename table in
     module-rename-map.md (old module from RELEASE → new module, pick by
     argument shape).
   - **Still unresolved** → resolve manually and **append the row** to
     module-rename-map.md.
3. **VxWorks serial / IP-carrier setup has no soft-IOC equivalent** — see the
   dedicated handling below.

#### 2c-i. VxWorks serial & IP carriers (kept as entities)

These map to **real entities that ibek re-emits** — do **not** drop them, and do
**not** route serial through a terminal server. The container runs with the
serial hardware **passed through** as `/dev/tty*` devices. The derivations below
are exact (verified against `tests/samples/bl15i-va-ioc-01.yaml`); the key insight
is that the entity models compute `cardid = 10·carrier.slot + ipslot`, so the
reverse direction recovers `ipslot` from the `cardid` in the boot script.

- **Carriers.** `IPACn = ipacEXTAddCarrier(&EXTHy8002, "<slot> <intLevel> <vec>")`
  → `ipac.Hy8002` with `slot` = first token. The `IPACn` variable is the
  **carrier reference** used by the cards below. (`ipac.Hy8002` has **no**
  `interrupt_vector` param — its `<vec>` is dropped; see the vector rule.)
- **IO card.** `Hy8001Configure(cardid, slot, vec, …, scan, 0, invertin, invertout)`
  → `ipac.Hy8001` (`slot` = arg 2, `interrupt_vector` = the `Vec` for arg 3,
  `scan`, `invertin`/`invertout` as bools, `direction`).
- **Serial IP modules.** `DLS8515Configure(cardid, IPACn, vec, "ty")` /
  `DLS8516Configure(...)` → `DLS8515.DLS8515` / `DLS8515.DLS8516`:
  - `carrier` = the `ipac.Hy8002` for `IPACn`
  - **`ipslot = cardid − 10·carrier.slot`** (e.g. card `42`, slot `4` → ipslot `2`)
  - `name` = `<carrier.name>Module<ipslot>` (e.g. `…Slot4Module2`)
  - `interrupt_vector` = the `Vec` for `vec`
- **ADC IP modules.** `Hy8401ipConfigure(cardid, IPACn, ipslot, vec, …)` →
  `Hy8401ip.Hy8401`: here `ipslot` is **explicit** (arg 3) and equals
  `cardid − 10·carrier.slot` (use it as a consistency check); remaining args
  (`intEnable`, `aiType`, `externalClock`, `clockRate`, `inhibit`, `samples`,
  `spacing`, `triggered`) map positionally.
- **Interrupt vectors.** The **absolute vector numbers in the boot script do not
  matter** — `epics.InterruptVectorVME` reserves a vector dynamically at runtime.
  Just create one `InterruptVectorVME` (`Vec1`, `Vec2`, …) for each card that
  takes a vector and have the card reference it (`Hy8001` → 1, each `DLS8515`/
  `DLS8516` → 1, each `Hy8401` → 1). Do not reverse-map the original numbers and
  do not fuss over reproducing any extra reserved/unreferenced vectors the XML
  path happened to emit — only the card→vector references are functionally
  significant.
- **Serial ports → `asyn.AsynSerial` with `/dev/tty` passthrough.**
  `drvAsynSerialPortConfigure("ty_40_0", "/ty/40/0", …)` →
  `asyn.AsynSerial name: ty_40_0  port: /dev/tty400`. Deterministic rewrite
  `/ty/<card>/<line>` → `/dev/tty<card><line>` (e.g. `/ty/41/7` → `/dev/tty417`).
  No host:port, no external info.
- **Serial line params → `DLS8515.DLS8515channel`.**
  `DLS8515DevConfigure("/ty/<cardid>/<line>", baud, data, stop, parity, …)` →
  `DLS8515.DLS8515channel` with `card` = the `DLS8515`/`DLS8516` entity whose
  `cardid` matches, `channel` = `<line>`. **Emit `baud`/`data`/`stop`/`parity`
  only when non-default** (`9600`/`8`/`1`/`N`) — the model's `pre_init` guards
  each with `{% if … %}` so defaults produce no output.
- `HostlinkInterposeInit` + `finsDEVInit("<name>.Hostlink", "<port>")` → the FINS
  module's interpose/port entity, bound to the asyn port `<port>`.

### 2c-ii. Reverse `pre_init` templates (Track B params)

For each matched Track B entity, align args to the `{{ param }}` slots of its
`pre_init`. Watch for **lossy** transforms not invertible from the st.cmd alone:

- `{{ x.split(' : ')[0] }}` — st.cmd holds only the first fragment.
- `{{ x | int }}` / `%02d` — formatting; leading zeros may be lost.
- `{% if y %}…{% else %}…{% endif %}` — arg **count** signals which branch fired.

Resolve lossy/missing params by joining to the device source (Track A
substitutions, or the compiled `_expanded.db`) on the shared **port name**. Read
the module `.template` at its RELEASE path to know which macros each entity needs
— see [ibek-concepts](../skills/ibek-concepts/SKILL.md) for `databases.args`.

### 2d. Inject standard boilerplate entities

Every converted IOC gets these conventional entities even though they are not
1:1 lines in the st.cmd (compare any existing converted IOC in the services
repo):

- `epics.EpicsEnvSet name: EPICS_TZ value: GMT0BST`
- `epics.EpicsEnvSet name: STREAM_PROTOCOL_PATH value: /epics/runtime/protocol/`
  (global — do **not** also add to entity `pre_init`, per CLAUDE.md)
- `devIocStats.iocAdminSoft IOC: '{{ ioc_name | upper }}'`
- `epics.EpicsCaMaxArrayBytes` (from the `EPICS_CA_MAX_ARRAY_BYTES` envSet)
- `autosave.Autosave P: '<prefix>:'` (collapsing all `save_restore*` lines).
  Beware the pass-0/pass-1 restore gotcha —
  [autosave-conversion.md](../skills/shared/autosave-conversion.md)
- `pvlogging.PvLogging` if the IOC used pvlogging

### 2e. Assemble and enumerate

Write the reconstructed entities to `$INSTANCE_DIR/config/ioc.yaml` (header,
`ioc_name`, `description`, `entities:` — mirror the format of an existing
converted IOC). Then, exactly as `/ioc-convert` Phase 1e, enumerate every
`module.Entity` and collect those missing a support YAML or entity model,
checking **both** submodules. Tell the user: "Reconstructed N entities; M
modules need support YAMLs: [list]."

---

## Phases 3–4 — Support YAMLs + generate (reuse /ioc-convert)

From here the workflow is identical to `/ioc-convert`. Read
[ioc-convert.md](ioc-convert.md) and follow its **Phase 2 (parallel support YAML
creation)**, **Phase 3 (generate runtime assets)**, and **Phase 4 (parallel
error fixing)** verbatim, using the module path table from Phase 1b and the
isolated `EPICS_ROOT` from Phase 0.

---

## Phase 5 — Validate by round-trip (main agent)

This is the key advantage of raw conversion: **the original built artifacts are
right there**, so validate functional equivalence directly rather than against a
VxWorks boot script.

### 5a. st.cmd equivalence

Read the generated `$EPICS_ROOT/runtime/st.cmd` and diff it against the original
`$1/iocBoot/ioc<IOC-PREFIX>/st<IOC-PREFIX>.src`. For every driver/config call in
the original, confirm an equivalent appears in the generated st.cmd (allowing for
the verb renames in module-rename-map.md and the expected
[vxworks-to-rtems-differences.md](../skills/shared/vxworks-to-rtems-differences.md)).
Flag any original config call with **no** generated equivalent — that is a
dropped or unmatched entity.

### 5b. db / ioc.subst equivalence

The strongest check for db-driven IOCs: compare the generated `ioc.subst` (or db)
against the original device source. If `_expanded.substitutions` existed, diff
the generated substitutions against it block-for-block — same template files,
same row count per block, same macro values. Otherwise compare record names
(PV `P`+`R`) and key macros against `$1/db/<IOC-PREFIX>_expanded.db`.
Mismatched or missing records indicate a wrong reversed parameter in
Phase 2c.

### 5c. Optional XML cross-check

If the RELEASE header names an `.xml` source **and it still exists**, you may
additionally run `uv run builder2ibek xml2yaml <xml> --yaml /tmp/gt.yaml` and
compare — but expect the XML to use higher-level **composite** entities that
expand into many st.cmd lines, so this is a *functional* cross-check, never a
line-by-line YAML diff. Skip silently if no XML.

### 5d. Refresh global schema

If any support YAMLs were created/modified, refresh the editor schema so new
entity types resolve:

```bash
EPICS_ROOT=/epics ./update-schema
```

---

## Phase 6 — Report (main agent)

Do **not** commit. Report:

1. **Reconstruction summary** — Track A device entities recovered (and from
   which source: substitutions vs db) and Track B plumbing entities; verbs
   matched directly vs via the rename table; any new rename rows appended to
   module-rename-map.md.
2. **Serial / IP-carrier entities** (2c-i) — confirm each `asyn.AsynSerial`
   (`/ty/N/M` → `/dev/ttyNM`), `DLS8515channel`, and the `ipac`/`DLS8515`/
   `Hy8401ip` carrier/card entities were emitted. These run with `/dev/tty`
   passthrough — **not** a terminal server — so they are **not** blockers.
3. **Unmatched / lossy items** — st.cmd calls or db clusters with no entity
   match, parameters that could not be recovered, anything needing manual review.
4. **Round-trip results** — st.cmd and substitutions/db equivalence from Phase 5.
5. **Files changed** and **suggested git commands** (same form as `/ioc-convert`
   Phase 5d).
