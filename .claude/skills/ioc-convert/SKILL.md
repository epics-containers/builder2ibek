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

This skill uses **parallel subagents** for support YAML creation and error
fixing, to keep the main context small and speed up large IOCs.

---

## Phase 1 — Setup and XML conversion (main agent)

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

Read the generated `ioc.yaml`. **Do not read large referenced files yet** —
that work is delegated to subagents in Phase 2.

Scan quickly for converter issues that must be fixed before support YAML work:

**Spurious attributes** — `name:` fields on leaf entities that don't need them
(e.g. hidenRGA, cmsIon). These should be dropped by a converter. If a converter
doesn't exist yet, create `src/builder2ibek/converters/<module>.py`.
Converters are auto-discovered — no registration needed.

**Attributes needing transformation** — values that need renaming, numeric
transformation, or removal before ibek sees them. Add or update the converter
rather than editing ioc.yaml by hand.

**dlsPLC entities** — read
[docs/reference/dlsplc-migration.md](../../../docs/reference/dlsplc-migration.md)
and check the "What requires manual attention" table. Every case listed there
(`vacuumValveRead2`, `vacuumPump.*`, `flow.flow_asyn`, `vacuumValveBistable`,
partial `temperature.*`) should be fixed by implementing or improving the
relevant converter — not by editing ioc.yaml by hand.

**Converters that emit multiple entities** — when a single XML element must
produce more than one ibek entity, use `entity.add_entity(extra)` and
`entity.delete_me()`. **Critical**: pass plain `dict` objects to
`add_entity()`, never `Entity(...)`. Creating a new `Entity` resets the
class-level `_extra_entities` list, silently dropping all previously added
extras:
```python
entity.add_entity({"type": "dlsPLC.read100", "device": entity.device, ...})
entity.add_entity({"type": "dlsPLC.read100", "device": entity.device, ...})
entity.delete_me()
```

After any converter change: re-run xml2yaml and repeat 1b until the ioc.yaml
is clean of converter-fixable issues.

### 1c. Enumerate modules needing support YAMLs

Parse the final ioc.yaml. For each entity type `<module>.<Entity>`:

1. Check whether the support YAML already exists:
   - `ibek-support-dls/<module>/<module>.ibek.support.yaml`
   - `ibek-support/<module>/<module>.ibek.support.yaml`
2. If it exists, check whether the specific entity model is present inside it.
3. Collect all `<module>` names where the support YAML is **missing** or
   **missing the required entity model**.

Also note for each module:
- The entity type names used (e.g. `mks937b.mks937bImg`)
- All parameter names and sample values from the ioc.yaml entities

Tell the user: "Found N modules needing support YAMLs: [list]. Launching
parallel subagents."

---

## Phase 2 — Parallel support YAML creation (subagents)

**Launch one `general-purpose` subagent per module** that needs a support YAML
or entity model. Launch all of them in a single message so they run in
parallel.

Each subagent operates independently and writes its own files directly.
Since modules map to different file paths, concurrent writes are safe.

### Subagent prompt template

For each module, construct a prompt containing **all** of the following:

---
**Briefing** (include verbatim in every subagent prompt):

> You are writing an ibek support YAML for an EPICS support module.
> The ibek support YAML format defines `entity_models` — each one maps to a
> Python class in the module's `builder.py`. Key rules:
>
> - Parameter names in the ibek YAML must match XML attribute names exactly
>   (so `xml2yaml` round-trips correctly).
> - `TemplateFile` in builder.py → `databases[].file` in the ibek YAML.
> - `PostIocInitialise`/`Initialise`/`InitialiseOnce` methods → `post_init`/`pre_init`.
> - `InitialiseOnce` → add `when: first` to the pre_init command.
> - `pre_init`, `databases`, `post_init` values are Jinja2 templates with
>   entity parameters as context. `{{P}}` resolves to parameter `P`.
> - `databases.args`: `key: value` pairs passed as macros to `dbLoadRecords`.
>   Omitting the value uses the parameter of the same name. `.*:` passes all
>   parameters through (correct for pure `AutoSubstitution` entities).
> - `name` parameter → `type: id` only when another entity cross-references
>   this one (asyn port creators). For leaf entities, drop `name`.
> - `PORT` parameter → `type: object` (asyn port reference).
> - `STREAM_PROTOCOL_PATH` is handled globally — do NOT add it to pre_init.
> - Macros without a default in the compiled `.db` file must be ibek parameters.
>   Macros with a default should be optional parameters so instances can override.
> - Support YAML path (DLS-specific): `ibek-support-dls/<module>/<module>.ibek.support.yaml`
> - Support YAML path (community): `ibek-support/<module>/<module>.ibek.support.yaml`
> - Install file path: `ibek-support-dls/<module>/<module>.install.yml`
>   (note: `.yml` not `.yaml`)
>
> Always look at existing examples first:
> - `ibek-support-dls/hidenRGA/hidenRGA.ibek.support.yaml` — 4 variants, optional params with defaults
> - `ibek-support-dls/cmsIon/cmsIon.ibek.support.yaml` — name dropped (leaf entity)
> - `ibek-support-dls/digitelMpc/digitelMpc.ibek.support.yaml`
>
> Find builder.py at:
> `/dls_sw/prod/R3.14.12.7/support/<module>/<version>/etc/builder.py`
> (list `/dls_sw/prod/R3.14.12.7/support/<module>/` to find the version)
>
> Find db files at:
> `/dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/`
> Check `# % macro` lines to identify required vs optional macros.
>
> Do NOT call `./update-schema` — the main agent will do that after all
> subagents complete.

---

**Module-specific context** (filled in by main agent per module):

> Module name: `<module>`
>
> Entity types used in this IOC (from ioc.yaml):
> - `<module>.<EntityA>` — parameters seen: `P=BL19I-VA-IMG-01`, `name=IMG01`, ...
> - `<module>.<EntityB>` — parameters seen: ...
>
> Check both `ibek-support-dls/<module>/` and `ibek-support/<module>/` before
> creating anything — the community version may already exist.
>
> Write (or update) the support YAML. If the module is DLS-specific, also
> write the `install.yml`. Return a brief summary of what you created/changed.

---

### After all subagents complete

Collect their summaries. Check whether any subagent reported a failure or
uncertainty (e.g. "could not find builder.py" or "unclear what pre_init
should be"). Note these for manual follow-up.

---

## Phase 3 — Generate runtime assets (main agent)

Set up the ibek environment:
```bash
mkdir -p /epics/ioc
ibek dev instance <services-repo>/services/$IOC_NAME
./update-schema
```

Run generation:
```bash
uvx --python 3.13 ibek runtime generate2 --no-pvi <services-repo>/services/$IOC_NAME/config
```

**If generation succeeds**, proceed directly to Phase 5.

**If generation fails**, group the errors by module and proceed to Phase 4.

---

## Phase 4 — Parallel error fixing (subagents)

Group all errors by the module they implicate. For each group, launch one
`general-purpose` subagent. Launch all in a single message.

**Distinguish the fix type for each error** before spawning, as it affects
whether the subagent also needs to re-run xml2yaml:

| Error | Fix type |
|---|---|
| Unknown entity type `foo.Bar` | Support YAML — add entity model |
| Unknown parameter `X` on `foo.Bar` | Support YAML — add parameter; or Converter — rename/drop attribute |
| Validation error on a field | Support YAML — fix type; or Converter — transform value |
| `object BL19I-VA-... not found` | Support YAML — change id field to `type: id` |
| `Field required` on a parameter | Support YAML — add `default:` |
| `database arg 'fooN' not found in context` | Support YAML — fix database args or add param aliases via Jinja2 |
| Attribute value wrong or unwanted | Converter — re-run xml2yaml after fix |

Errors that require **converter** fixes cannot be fully resolved by a subagent
alone — the subagent should make the converter fix and report back; the main
agent then re-runs xml2yaml before the next generate2 attempt.

### Fix subagent prompt template

For each error group, construct a prompt containing:

---
**Briefing** (include verbatim — same ibek rules as Phase 2 briefing above):
> [paste the full briefing block from Phase 2]

---
**Error-specific context** (filled in by main agent):

> Module: `<module>`
>
> Error(s) from `ibek runtime generate2`:
> ```
> <paste exact error messages>
> ```
>
> Current support YAML (`ibek-support-dls/<module>/<module>.ibek.support.yaml`):
> ```yaml
> <paste full current content>
> ```
>
> Relevant db file(s) to check: `/dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/<file>.db`
>
> Fix the support YAML (and/or converter if needed). Do NOT run ./update-schema
> or xml2yaml — the main agent handles re-runs. Return a brief summary of what
> you changed and whether a converter fix was also needed.

---

### After all fix subagents complete

1. If any subagent made converter fixes: re-run xml2yaml.
2. Run `./update-schema`.
3. Re-run `generate2`.
4. If errors remain, repeat Phase 4 (but at most 3 iterations — if errors
   persist after 3 rounds, report to the user and ask for guidance).

**Object-reference chain note**: if you see `object BL19I-VA-... not found`,
check the `type:` of the id field in the referenced entity's support YAML —
it must be `type: id` not `type: str`. Also check the `name` vs `device`
pattern: some modules use `name` as `type: id` (e.g. `mks937b.mks937bImg` →
id = `IMG01`), others use `device` as `type: id` (e.g. `mks937a.mks937aImg`
→ id = `BL19I-VA-IMG-03`). Cross-referencing converters like `vacuumSpace.py`
must skip entities whose `name` is still present after conversion.

---

## Phase 5 — Validate and report (main agent)

### 5a. Validate st.cmd

Read `/epics/runtime/st.cmd`. Verify:

- Environment variables set correctly (`EPICS_TS_MIN_WEST`, `STREAM_PROTOCOL_PATH`)
- `drvAsynIPPortConfigure` calls present with correct port name and IP:port
- All `pre_init` commands present (StreamDevice protocol path, driver init calls)
- `iocInit` is present
- `seq(...)` or other `post_init` calls present where expected

Find the original VxWorks boot script:
```bash
ls /dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/
```
The beamline segment (`BLXX`) = first two dash-separated fields of the IOC name.
Then read:
```
/dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/<version>/bin/vxWorks-ppc604_long/<IOC-NAME>.boot
```

Expected differences (do not flag these as problems):

| Original (VxWorks) | Generated (container) | Notes |
|---|---|---|
| Serial port paths `/ty/40/0` etc. | `/dev/tty400` etc. | Normal VxWorks → Linux translation |
| `DLS8515DevConfigure(port, baud, ...)` for every port | `asynSetOption` only for non-default settings | Asyn defaults to 9600/8/1/N; only overrides needed |
| `STREAM_PROTOCOL_PATH = calloc/strcat(...)` with absolute prod paths | `epicsEnvSet STREAM_PROTOCOL_PATH /epics/runtime/protocol/` | Container-relative path — correct |
| `ErTimeProviderInit`, `installLastResortEventProvider`, `syncSysClock` | Not present | VxWorks timing calls; not used in containers |
| `ld < bin/...munch`, `dbLoadDatabase "dbd/..."` | `dbLoadDatabase dbd/ioc.dbd` | VxWorks binary load replaced by standard dbd load |
| `asSetFilename` with absolute prod path | Container-relative `/epics/support/pvlogging/src/access.acf` | Expected |

If commands from the original are missing and not in the table, the relevant
entity model's `pre_init` or `post_init` section needs updating.

### 5b. Validate ioc.subst

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
> `/db` include paths, which are not present here. For now, validate by
> inspection against the original `.db` files.

### 5c. Report and suggest commits

Once clean, **do not commit anything**. Report to the user:

1. **Conversion summary** — what entities were generated, modules handled by
   subagents, any subagent uncertainties that need manual review
2. **st.cmd comparison** — key differences from the original builder boot script
3. **ioc.subst validation** — db files, macros, and values match expectations
4. **Files changed** — list what was created/modified and in which repo
5. **Suggested git commands** for the user to run when satisfied:

```bash
# In /workspaces/<beamline>-services — new IOC instance (always needed):
git -C /workspaces/<beamline>-services add services/<ioc-name>/
git -C /workspaces/<beamline>-services commit -m "Add <ioc-name> (converted from builder XML)"

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
