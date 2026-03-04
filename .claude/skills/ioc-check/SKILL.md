---
name: ioc-check
description: Run ibek generate on an existing converted IOC and report errors, or validate st.cmd and ioc.subst against the original boot script.
argument-hint: <path/to/IOC.xml> [<path/to/services-repo>]
disable-model-invocation: true
---

# IOC Check Workflow

Check an already-converted IOC instance: run `ibek runtime generate2` and
report any errors. If generation succeeds, compare the generated `st.cmd`
against the original VxWorks boot script and validate `ioc.subst`.

**This skill is read-only.** It makes no changes to converters, support YAMLs,
ioc.yaml, or any other file.

---

## Step 1 — Resolve services repo and IOC name

Follow [services-repo-resolution.md](../shared/services-repo-resolution.md)
using `$1` (if provided) or the IOC prefix from `$0`.

Derive `IOC_NAME` = lowercase XML filename without extension.

`INSTANCE_DIR` = `<services-repo>/services/$IOC_NAME`

**Pre-check**: if `$INSTANCE_DIR/config/ioc.yaml` does not exist, stop and
tell the user to run `/ioc-convert $0` first.

---

## Step 2 — Set up ibek environment

Create an isolated `EPICS_ROOT` for this session so multiple checks can run in
parallel without conflicting:
```bash
export EPICS_ROOT=$(mktemp -d /tmp/epics-ioc-check-XXXXXX)
mkdir -p $EPICS_ROOT/ioc
ibek dev instance <services-repo>/services/$IOC_NAME
./update-schema
```

`EPICS_ROOT` must be exported so that `ibek` and `./update-schema` use the
isolated directory tree instead of the shared `/epics/`.

---

## Step 3 — Run generate2

```bash
uvx --python 3.13 ibek runtime generate2 --no-pvi <services-repo>/services/$IOC_NAME/config
```

**If generation fails**, categorise and report the errors using the table in
[error-categorization.md](../shared/error-categorization.md), then **stop** —
do not make any fixes.

**If generation succeeds**, continue to Steps 4–5.

---

## Step 4 — Validate st.cmd

Read `$EPICS_ROOT/runtime/st.cmd`.

Find the original VxWorks boot script following
[find-boot-script.md](../shared/find-boot-script.md).

Compare the original and generated scripts. For each meaningful command in the
original, report whether the equivalent is present in `st.cmd`. Flag any
command that is absent from `st.cmd` and is **not** in the expected-differences
table: [vxworks-to-rtems-differences.md](../shared/vxworks-to-rtems-differences.md).

---

## Step 5 — Validate ioc.subst

Read `$EPICS_ROOT/runtime/ioc.subst`. For each `file` block verify:
- The db file path looks plausible
- All expected macros are present in the `pattern`
- Macro values match the ioc.yaml entity parameters

> **`entity_enabled` and `type` in pattern columns**: When a support YAML uses
> `.*:` in `databases.args`, ibek passes all entity attributes as db macros —
> including `entity_enabled` (added by ibek to every entity model) and `type`
> (the entity type string). These will appear as extra columns in `ioc.subst`
> pattern blocks. They are **not** referenced in the db file and are harmless —
> do not flag them as errors.

To check what macros a db file expects:
```bash
grep "^# % macro" /dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/<file>.db
```

**db-compare** (record-level comparison): if the original expanded DB is
accessible, run:
```bash
uv run builder2ibek db-compare \
    /dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/<version>/db/<IOC-NAME>_expanded.db \
    $EPICS_ROOT/runtime/ioc.db \
    --output /tmp/compare.diff
```
then read `/tmp/compare.diff` and report missing records, extra records, and
field differences.

Note: `$EPICS_ROOT/runtime/ioc.db` is only generated inside a Generic IOC
devcontainer where `msi` can expand `ioc.subst` with all support `/db` paths
present. If it is absent, skip db-compare and validate by inspection only.

---

## Step 6 — Report

Report to the user:

1. **Generate status** — clean or list of errors (categorised)
2. **st.cmd comparison** — commands matched, expected differences noted,
   any unexpected missing commands highlighted
3. **ioc.subst validation** — number of db file blocks, any macro concerns,
   db-compare summary if run
4. **No files changed** — confirm this skill made no modifications
