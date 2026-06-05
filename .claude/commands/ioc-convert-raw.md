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
| `iocBoot/ioc*/st*.src` | driver/config calls (verb + args) + boilerplate |
| `db/*_expanded.db` (compiled) | record macros (P, R, sizes…) joined to st.cmd by **port name** |

> **Do not defer to `/ioc-convert` even if a `.xml` reference appears in the
> RELEASE header.** This command exists to handle IOCs with no XML; an existing
> XML is only ever useful as an optional ground-truth cross-check (Phase 6b).

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

### 1c. Locate the startup script and compiled db

- Startup script: `$1/iocBoot/ioc<IOC-PREFIX>/st<IOC-PREFIX>.src`. Use the
  `.src` (the actual command sequence), **not** the `.sh` wrapper.
- Compiled db: read the `dbLoadRecords` lines at the end of the `.src` — they
  point at `db/<IOC-PREFIX>_expanded.db` (and sometimes `db/<IOC-PREFIX>.db`).
  These compiled files in `$1/db/` are the **authoritative source of record
  macros** (per CLAUDE.md: macros come from the compiled `.db`, never `.subst`).

### 1d. Derive a terse description

A few words describing what the IOC controls, inferred from the prefix and the
dominant drivers in the st.cmd (e.g. "Aravis diagnostic cameras", "Geobrick
motion"). No full sentences.

---

## Phase 2 — Reconstruct entities (main agent)

This is the heart of the command. Work through the `.src` top to bottom.

### 2a. Build the command index

Across **both** support dirs, extract every entity's `pre_init`/`post_init`
template and the leading function-name token:

```bash
grep -rn "pre_init\|post_init" ibek-support*/*/*.ibek.support.yaml
```

For each module the IOC actually uses (from the RELEASE table), read its support
YAML so you have the full `pre_init` Jinja templates and parameter lists ready.
**Always check BOTH `ibek-support/` and `ibek-support-dls/`** — a module lives in
exactly one (no duplicates).

### 2b. Classify and match each st.cmd line

Tokenize each non-comment, non-blank line into `(verb, args[])`, respecting
quotes. Then classify per
[module-rename-map.md](../skills/shared/module-rename-map.md):

1. **Boilerplate** (`cd`, `dbLoadDatabase`, `*_registerRecordDeviceDriver`,
   `iocInit`, `save_restore*`, `set_*restoreFile`, `directoryWait`,
   `epicsEnvSet`) → map to standard entities or drop, per the boilerplate table
   in module-rename-map.md.
2. **Driver/config calls** → match the verb to a `module.entity`:
   - **Direct match first**: the verb appears verbatim in exactly one entity's
     `pre_init`/`post_init`. Use it.
   - **On a miss**: the verb was renamed in migration. Consult the verb-rename
     table in module-rename-map.md. Find the old module in the RELEASE table,
     look up the new module, pick the entity whose `pre_init` has the same
     **argument shape** (count + quoted-vs-int positions).
   - **Still unresolved**: resolve manually, then **append the new row to
     module-rename-map.md** so future runs are deterministic.

### 2c. Reverse the template to recover parameters

For each matched entity, align the st.cmd args to the `{{ param }}` slots of its
`pre_init` template. Watch for **lossy** transforms that cannot be inverted from
the st.cmd alone:

- `{{ x.split(' : ')[0] }}` — st.cmd holds only the first fragment.
- `{{ x | int }}` / `%02d` — formatting, leading zeros may be lost.
- `{% if y %}…{% else %}…{% endif %}` — arg **count** signals which branch
  fired; recover `y`'s presence from that.

Resolve every lossy or missing parameter by **joining to the compiled
`_expanded.db` on the shared port name**: the `PORT` string (e.g. `D1.cam`)
appears in both the config call and the db records, so its `P`, `R`, and sizing
macros (`XSIZE`, `NELEMENTS`, `HIST_SIZE`, …) come straight from the db. Read the
module's `.template` (at its RELEASE path) to know which macros each entity needs
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
- `autosave.Autosave P: '<prefix>:'` (collapsing all `save_restore*` lines)
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

Compare the records produced by the generated `ioc.subst`/db against the original
`$1/db/<IOC-PREFIX>_expanded.db`. The record names (PV `P`+`R`) and key macros
must match. Mismatched or missing records indicate a wrong reversed parameter in
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

1. **Reconstruction summary** — entities recovered, verbs matched directly vs via
   rename table, any new rename rows appended to module-rename-map.md.
2. **Unmatched / lossy items** — st.cmd calls with no entity match, parameters
   that could not be recovered from the db, anything needing manual review.
3. **Round-trip results** — st.cmd and db equivalence findings from Phase 5.
4. **Files changed** and **suggested git commands** (same form as `/ioc-convert`
   Phase 5d).
