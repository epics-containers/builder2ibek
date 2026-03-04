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

## Phase 0 — Create isolated EPICS_ROOT (main agent)

Create a unique temporary directory for this agent's ibek state. This ensures
multiple `/ioc-convert` invocations can run in parallel without conflicting
over `/epics/runtime/`, `/epics/ibek-defs/`, or `/epics/ioc/`.

```bash
export EPICS_ROOT=$(mktemp -d /tmp/epics-ioc-convert-XXXXXX)
```

All subsequent `ibek` and `./update-schema` commands in this session (and in
subagent prompts) must have `EPICS_ROOT` set to this value.

---

## Phase 1 — Setup and XML conversion (main agent)

### 1a. Resolve the services repo

Follow [services-repo-resolution.md](../shared/services-repo-resolution.md)
using `$1` (if provided) or the IOC prefix from `$0`.

- If `INSTANCE_DIR` already exists:
  - Check `$INSTANCE_DIR/values.yaml` — if it contains `dev-c7:`, this is a
    legacy IOC. Remove the entire folder (`rm -rf $INSTANCE_DIR`) and recreate
    it from `.ioc_template` (fall through to the "does not exist" case below).
  - Otherwise, if `config/ioc.yaml` is present: run `git -C <services-repo> status`
    — if ioc.yaml is modified or untracked, ensure it is committed or stashed
    before overwriting.
- If `INSTANCE_DIR` does not exist:
  - If `<services-repo>/services/.ioc_template/` exists:
    `cp -r <services-repo>/services/.ioc_template/ $INSTANCE_DIR`
  - Otherwise: `mkdir -p $INSTANCE_DIR/config/`

### 1b. Resolve support module paths

Read the `_RELEASE` file next to the XML following
[find-module-path.md](../shared/find-module-path.md). Record a **module path
table** mapping module name → resolved path, e.g.:
```
ethercat → /dls_sw/prod/R3.14.12.7/support/ethercat/7-2
rackFan  → /dls_sw/prod/R3.14.12.7/support/rackFan/2-12
```

This table will be passed to subagents in Phases 2 and 4.

### 1c. Run the conversion

```bash
uv run builder2ibek xml2yaml $0 --yaml $INSTANCE_DIR/config/ioc.yaml
```

### 1d. Review ioc.yaml and fix converters

Read the generated `ioc.yaml`. **Do not read large referenced files yet** —
that work is delegated to subagents in Phase 2.

Scan quickly for converter issues that must be fixed before support YAML work:

**Spurious `name:` fields** — only drop `name` from entities that are truly
leaf (not cross-referenced). Before dropping, check all `type: object` params
in the module's support YAML and sample IOC YAMLs to verify nothing references
the entity by name. When in doubt, **keep `name: type: id`** — it is safe to
keep but dangerous to drop. If a converter is needed, create
`src/builder2ibek/converters/<module>.py` (auto-discovered, no registration).

**Attributes needing transformation** — values that need renaming, numeric
transformation, or removal before ibek sees them. Add or update the converter
rather than editing ioc.yaml by hand.

**dlsPLC entities** — read
[docs/reference/dlsplc-migration.md](../../../docs/reference/dlsplc-migration.md)
and check the "What requires manual attention" table. Every case listed there
should be fixed by implementing or improving the relevant converter.

**Converters that emit multiple entities** — when a single XML element must
produce more than one ibek entity, use `entity.add_entity(extra)` and
`entity.delete_me()`. **Critical**: pass plain `dict` objects to
`add_entity()`, never `Entity(...)`.

**Auto-substitution entities (`auto_*`)** — entity types like
`module.auto_xxxx` correspond to a database template `xxxx.template` in the
`db/` directory of the support module. These need a support YAML entity model
with just parameters and a `databases` section — no `pre_init` or `post_init`.

After any converter change: re-run xml2yaml and repeat 1d until the ioc.yaml
is clean of converter-fixable issues.

### 1e. Enumerate modules needing support YAMLs

Parse the final ioc.yaml. For each entity type `<module>.<Entity>`:

1. Check whether the support YAML already exists — **always check BOTH
   submodules** (`ibek-support-dls/<module>/` and `ibek-support/<module>/`)
   before concluding anything is missing.
2. If it exists, check whether the specific entity model is present inside it.
3. Collect all modules where the support YAML or entity model is missing.

Also note for each module: entity type names used and sample parameter values.

Tell the user: "Found N modules needing support YAMLs: [list]. Launching
parallel subagents."

---

## Phase 2 — Parallel support YAML creation (subagents)

**Launch one `general-purpose` subagent per module** that needs a support YAML
or entity model. Launch all in a single message so they run in parallel.

### Subagent prompt template

For each module, construct a prompt:

> Read `/workspaces/builder2ibek/.claude/skills/support-create/SKILL.md` and
> follow its instructions to create a support YAML for the following module.
>
> Module name: `<module>`
>
> Known path from _RELEASE: `<resolved-path>`
>
> Entity types used in this IOC (from ioc.yaml):
> - `<module>.<EntityA>` — parameters seen: `P=BL19I-VA-IMG-01`, `name=IMG01`, ...
> - `<module>.<EntityB>` — parameters seen: ...
>
> **CRITICAL — no duplicates:** A module must exist in exactly ONE of
> `ibek-support/` or `ibek-support-dls/`. Check both directories first. If
> the module already exists in one location, use that location — never
> create a second copy in the other submodule.
>
> Write (or update) the support YAML. Return a brief summary of what you
> created/changed.

### After all subagents complete

Collect their summaries. Check whether any subagent reported a failure or
uncertainty. Note these for manual follow-up.

---

## Phase 3 — Generate runtime assets (main agent)

Set up the ibek environment (using the isolated `EPICS_ROOT` from Phase 0):
```bash
mkdir -p $EPICS_ROOT/ioc
ibek dev instance <services-repo>/services/$IOC_NAME
./update-schema
```

If any converters or support YAMLs were created or modified in Phase 2, run
the builder2ibek test suite before generation:
```bash
uv run pytest
```
Fix any failures before continuing.

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

### Fix subagent prompt template

> Read `/workspaces/builder2ibek/.claude/skills/support-fix/SKILL.md` and
> follow its instructions to fix the following errors.
>
> Module: `<module>`
>
> Known path from _RELEASE: `<resolved-path>`
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
> Relevant db file(s) to check: `<known-path>/db/<file>.db`
>
> Return a summary of what you changed and whether a converter fix was needed.

### After all fix subagents complete

1. If any subagent made converter fixes: re-run xml2yaml.
2. Run `./update-schema`.
3. Run `uv run pytest` — fix any regressions before proceeding.
4. Re-run `generate2`.
5. If errors remain, repeat Phase 4 (but at most 3 iterations — if errors
   persist after 3 rounds, report to the user and ask for guidance).

---

## Phase 5 — Validate and report (main agent)

### 5a. Validate st.cmd

Read `$EPICS_ROOT/runtime/st.cmd`.

Find the original VxWorks boot script following
[find-boot-script.md](../shared/find-boot-script.md).

Compare the original and generated scripts. For each meaningful command in the
original, check whether the equivalent is present in `st.cmd`. Flag any
command that is absent and is **not** in the expected-differences table:
[vxworks-to-rtems-differences.md](../shared/vxworks-to-rtems-differences.md).

### 5b. Validate ioc.subst

Read `$EPICS_ROOT/runtime/ioc.subst`. For each `file` block verify:
- Correct db file path
- All required macros present in `pattern`
- Macro values match the ioc.yaml entity parameters

> **`entity_enabled` and `type` in pattern columns**: When a support YAML uses
> `.*:` in `databases.args`, ibek passes all entity attributes as db macros —
> including `entity_enabled` and `type`. These are harmless — do not flag them.

To check what macros a db file expects:
```bash
grep "^# % macro" /dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/<file>.db
```

### 5c. Report and suggest commits

Once clean, **do not commit anything**. Report to the user:

1. **Conversion summary** — what entities were generated, modules handled by
   subagents, any subagent uncertainties that need manual review
2. **st.cmd comparison** — key differences from the original builder boot script
3. **ioc.subst validation** — db files, macros, and values match expectations
4. **Files changed** — list what was created/modified and in which repo
5. **Suggested git commands** for the user to run when satisfied:

```bash
# In /workspaces/<beamline>-services — new IOC instance:
git -C /workspaces/<beamline>-services add services/<ioc-name>/
git -C /workspaces/<beamline>-services commit -m "Add <ioc-name> (converted from builder XML)"

# In /workspaces/builder2ibek — only if support YAMLs or converters changed:
git -C /workspaces/builder2ibek add ibek-support-dls/<module>/
git -C /workspaces/builder2ibek add ibek-support/<module>/
git -C /workspaces/builder2ibek add src/builder2ibek/converters/
git -C /workspaces/builder2ibek commit
```
