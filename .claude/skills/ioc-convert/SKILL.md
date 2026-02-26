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

The services repo path is `$1`. If `$1` is empty or not provided:

- Read `.claude/skills/ioc-convert/last-services-repo` (if it exists) and use
  that path as the services repo. Tell the user which repo is being reused.
- If the file does not exist, stop and ask the user to supply a services repo path.

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

Compare against the original builder boot script if available:
```
/dls_sw/work/R3.14.12.7/support/<BUILDER>/iocs/<IOC>/cmd/<IOC>.boot
```

If commands are missing, the entity model's `pre_init` or `post_init` section
needs updating.

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
