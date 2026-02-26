---
name: ioc-convert
description: Convert a builder XML IOC to ibek ioc.yaml, validate schema, generate runtime assets, and iterate until correct.
argument-hint: <path/to/IOC.xml> [<path/to/services-repo>]
disable-model-invocation: true
---

# IOC Convert and Validate Workflow

Convert builder XML `$0` to ibek `ioc.yaml` in the services repo `$1`, fix any
support YAML or converter issues, generate runtime assets, and verify `st.cmd`
and `ioc.subst` are correct.

---

## Step 1 — Convert XML to ioc.yaml

### 1a. Resolve the services repo

Resolve the services repo using the following priority order:

1. **Explicit argument** — if `$1` is provided, use it directly.

2. **Infer from IOC prefix** — derive the beamline name from the XML filename:
   - Extract the first `-`-delimited segment, e.g. `BL11I-CS-IOC-09.xml` → `BL11I`
   - Strip the leading `BL`, separate digits and trailing letter(s):
     `BL11I` → digits=`11`, letter=`I` → beamline=`i11`
   - Services repo name = `<beamline>-services`, e.g. `i11-services`
   - Look for it at `/workspaces/<services-repo-name>/`

3. **Fallback** — read `.claude/skills/ioc-convert/last-services-repo` if the
   inferred path does not exist on disk.

If the resolved path does not exist locally, clone it:
```bash
git clone git@gitlab.diamond.ac.uk:controls/containers/beamline/<services-repo-name> /workspaces/<services-repo-name>
```

Tell the user which services repo is being used and how it was resolved.

Once the services repo is known, write its absolute path to
`.claude/skills/ioc-convert/last-services-repo` (overwrite if present).

Derive `IOC_NAME` = lowercase XML filename without extension.

`INSTANCE_DIR` = `<services-repo>/services/$IOC_NAME`

- If `INSTANCE_DIR` already exists and `config/ioc.yaml` is present:
  - Run `git -C <services-repo> status` — if ioc.yaml is modified or untracked,
    ensure it is committed or stashed before overwriting.
- If `INSTANCE_DIR` does not exist:
  - If `<services-repo>/services/.ioc_template/` exists:
    `cp -r <services-repo>/services/.ioc_template/ $INSTANCE_DIR`
  - Otherwise: `mkdir -p $INSTANCE_DIR/config/`

Run the conversion:
```bash
uv run builder2ibek xml2yaml $0 --yaml $INSTANCE_DIR/config/ioc.yaml
```

### 1b. Review ioc.yaml and fix converters

Read the generated `ioc.yaml`. Look for:

**Spurious attributes** — `name:` fields on leaf entities that don't need them
(e.g. hidenRGA, cmsIon). These should be dropped by a converter. If a converter
doesn't exist yet, create `src/builder2ibek/converters/<module>.py` following
the pattern in [CLAUDE.md](../../../CLAUDE.md#adding-a-new-converter).

**Attributes needing transformation** — values that need renaming, numeric
transformation, or removal before ibek sees them. Add or update the converter
rather than editing ioc.yaml by hand.

**dlsPLC entities** — read
[docs/reference/dlsplc-migration.md](../../../docs/reference/dlsplc-migration.md)
and check the "What requires manual attention" table. Every case listed there
(`vacuumValveRead2`, `vacuumPump.*`, `flow.flow_asyn`, `vacuumValveBistable`,
partial `temperature.*`) should be fixed by **implementing or improving the
relevant converter** (e.g. `converters/vacuumValve.py`, `converters/vacuumPump.py`)
— not by editing ioc.yaml by hand. The transformation rules (valve×10→addr,
ilkA→ilk10, outaddr calculation, etc.) are all documented in that reference.

**Object-reference chains** — if entity A's parameter is `type: object` pointing
to entity B, then entity B's identifying field must be `type: id` (not `type: str`).
Example: `dlsPLC.externalValve.device` must be `type: id` so that
`vacuumSpace.space.valve0` (which is `type: object`) can resolve it. If you see
`object BL19I-VA-... not found` errors from generate2, check the `type:` of the
id field in the referenced entity's support YAML.

**`name` vs `device` as ibek id (mks937a vs mks937b pattern)** — some support
modules use `name` as `type: id` (e.g. `mks937b.mks937bImg` → id = `IMG01`),
while others use `device` as `type: id` (e.g. `mks937a.mks937aImg` → id =
`BL19I-VA-IMG-03`). When a cross-referencing converter (like `vacuumSpace.py`)
builds a builder-name→ibek-id translation map, it must skip entities whose
`name` is still present in `ioc.entities` after conversion (those entities
already register under their builder short-name, so no translation is needed).

**Converters that emit multiple entities** — when a single XML element must
produce more than one ibek entity (e.g. `temperaturePLCRead` → 2×
`dlsPLC.read100`), use `entity.add_entity(extra)` and `entity.delete_me()`.
**Critical**: pass plain `dict` objects to `add_entity()`, never `Entity(...)`.
Creating a new `Entity` resets the class-level `_extra_entities` list, silently
dropping all previously added extras. Example:
```python
entity.add_entity({"type": "dlsPLC.read100", "device": entity.device, ...})
entity.add_entity({"type": "dlsPLC.read100", "device": entity.device, ...})
entity.delete_me()
```

After any converter change: re-run xml2yaml and repeat 1b until the ioc.yaml is
clean.

---

## Step 2 — Set up ibek environment

```bash
mkdir -p /epics/ioc
ibek dev instance <services-repo>/services/$IOC_NAME
./update-schema
```

- `ibek dev instance` creates a symlink `/epics/ioc/config` → your instance config
- `./update-schema` symlinks all `ibek-support*` YAMLs into `/epics/ibek-defs/`
  and regenerates `/epics/ibek-defs/ioc.schema.json`

---

## Step 3 — Generate runtime assets (iterate until clean)

```bash
uvx --python 3.13 ibek runtime generate2 --no-pvi <services-repo>/services/$IOC_NAME/config
```

Runtime assets are written to `/epics/runtime/`: `st.cmd`, `ioc.subst`.

**If generation fails**, diagnose and fix:

| Error | Cause | Fix |
|---|---|---|
| Unknown entity type `foo.Bar` | No entity model exists | Check both `ibek-support-dls/foo/` (DLS modules) and `ibek-support/foo/` (community). Add the model following [create-support-yaml.md](../../../docs/tutorials/create-support-yaml.md). Run `./update-schema`. |
| Unknown parameter `X` on `foo.Bar` | Parameter missing or named differently in entity model | Check the support YAML; also check whether `src/builder2ibek/converters/foo.py` needs to rename or inject the attribute |
| Validation error on a field | Wrong ibek type, or XML value ibek can't accept | Fix the type in the support YAML; or add a converter to transform/drop the offending attribute |
| Attribute value wrong or unwanted | Maps through from XML incorrectly | Add or update `src/builder2ibek/converters/foo.py`; re-run xml2yaml, then re-run generation |
| `object BL19I-VA-... not found` | Referenced entity's id field is `type: str` instead of `type: id` | Change the id field to `type: id` in the referenced entity's support YAML. Run `./update-schema`. |
| `Field required` on a parameter | Parameter has no default and wasn't set in XML | Add `default:` to the parameter. Check builder.py for the auto-computed default value. |
| `database arg 'fooN' not found in context` | Support YAML database args reference a parameter name that the entity model doesn't define — often an index mismatch: entity has 0-indexed params (`gauge0..7`) but database args request 1-indexed macro names (`gauge1..8`) | Check the template's `# % macro` declarations and compare the index range against the entity model params. Consider whether to fix via the converter (injecting aliases into the entity dict before ibek sees it) or via explicit Jinja2 `gauge1: "{{ gauge0 }}"` mappings in the database args section. |

After any **support YAML** fix: `./update-schema` then re-run `uvx` generate.
After any **converter** fix: re-run `uv run builder2ibek xml2yaml`, then re-run `uvx` generate.

---

## Step 4 — Validate st.cmd

Read `/epics/runtime/st.cmd`. Verify:

- Environment variables set correctly (`EPICS_TS_MIN_WEST`, `STREAM_PROTOCOL_PATH`)
- `drvAsynIPPortConfigure` calls present with correct port name and IP:port
- All `pre_init` commands present (StreamDevice protocol path, driver init calls)
- `iocInit` is present
- `seq(...)` or other `post_init` calls present where expected

Compare against the original builder boot script if available.
Deployed IOCs are at:
```
/dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/<version>/bin/vxWorks-ppc604_long/<IOC-NAME>.boot
```
To find it, use (avoids the very slow `find /dls_sw` recursive search):
```bash
ls /dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/
```
For example for `BL19I-VA-IOC-01`:
```bash
ls /dls_sw/prod/R3.14.12.7/ioc/BL19I/BL19I-VA-IOC-01/
```
The beamline segment (`BL19I`) is the first two dash-separated fields of the IOC name.
The in-progress builder version may also be at:
```
/dls_sw/work/R3.14.12.7/support/<BUILDER>/iocs/<IOC>/cmd/<IOC>.boot
```

Expected differences between the original VxWorks boot script and the generated `st.cmd`:

| Original (VxWorks) | Generated (container) | Notes |
|---|---|---|
| Serial port paths `/ty/40/0` etc. | `/dev/tty400` etc. | Normal VxWorks → Linux translation |
| `DLS8515DevConfigure(port, baud, ...)` for every port | `asynSetOption` only for non-default settings | Asyn defaults to 9600/8/1/N; only overrides are needed |
| `STREAM_PROTOCOL_PATH = calloc/strcat(...)` with absolute prod paths | `epicsEnvSet STREAM_PROTOCOL_PATH /epics/runtime/protocol/` | Container-relative path — correct |
| `ErTimeProviderInit`, `installLastResortEventProvider`, `syncSysClock` after `ErConfigurePMC` | Not present | VxWorks timing calls; not used in containers |
| `ld < bin/...munch`, `dbLoadDatabase "dbd/..."` | `dbLoadDatabase dbd/ioc.dbd` | VxWorks binary load replaced by standard dbd load |
| `asSetFilename` with absolute prod path | Container-relative `/epics/support/pvlogging/src/access.acf` | Expected |

If commands from the original script are missing and are **not** in the table above, the relevant entity model's `pre_init` or `post_init` section needs updating.

---

## Step 5 — Validate ioc.subst

Read `/epics/runtime/ioc.subst`. Verify each `file` block:

- Correct db file path (matches the db file in the support module)
- All required macros present in `pattern`
- Macro values match the ioc.yaml entity parameters

To check what macros a db file expects:
```bash
grep "^# % macro" /dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/<file>.db
```

> **db-compare not available in this devcontainer**: Full record-level
> comparison requires running `msi` over `ioc.subst` with all support module
> `/db` include paths, which are not present here. This is a future enhancement
> for when the skill is run inside a Generic IOC devcontainer. For now, validate
> by inspection against the original `.db` files.

---

## Step 6 — Report and suggest commits

Repeat Steps 3–5 until:
- `ibek runtime generate2` completes without errors
- `st.cmd` and `ioc.subst` look correct by inspection

Once clean, **do not commit anything**. Instead, report to the user:

1. **Conversion summary** — what entities were generated, any issues noticed
2. **st.cmd comparison** — key differences from the original builder boot script
   (e.g. container-relative paths replacing absolute paths — expected and correct)
3. **ioc.subst validation** — db files, macros, and values match expectations
4. **Files changed** — list what was created/modified and in which repo
5. **Suggested git commands** for the user to run when satisfied:

```bash
# In /workspaces/i11-services — new IOC instance (always needed):
git -C /workspaces/i11-services add services/<ioc-name>/
git -C /workspaces/i11-services commit -m "Add <ioc-name> (converted from builder XML)"

# In /workspaces/builder2ibek — only if support YAMLs or converters changed:
git -C /workspaces/builder2ibek add ibek-support-dls/<module>/   # DLS-internal module
git -C /workspaces/builder2ibek add ibek-support/<module>/       # community module
git -C /workspaces/builder2ibek add src/builder2ibek/converters/ # converter
git -C /workspaces/builder2ibek add tests/samples/               # optional regression test
git -C /workspaces/builder2ibek commit
```

> **Note on submodules**: Entity models live in one of two submodules:
> - `ibek-support-dls/` — DLS-specific modules (hidenRGA, cmsIon, digitelMpc, dlsPLC, ...)
> - `ibek-support/` — Community modules (asyn, StreamDevice, iocStats, autosave, ...)
>
> Always check both before creating a new entity model — the community version
> may already exist in `ibek-support/`.
