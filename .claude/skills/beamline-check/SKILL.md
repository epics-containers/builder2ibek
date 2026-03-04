---
name: beamline-check
description: Run ioc-check on all IOCs in a beamline's services repo in parallel.
argument-hint: <beamline-prefix> [<path/to/services-repo>]
disable-model-invocation: true
---

# Beamline Check Workflow

Validate all converted IOCs for beamline `$0` (e.g. `i19` or `BL19I`) by
running `/ioc-check` on each one in parallel.

**This skill is read-only.** It makes no changes to any files.

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../shared/services-repo-resolution.md)
using `$1` (if provided) or the beamline prefix `$0`.

Accept both short (`i19`) and full (`BL19I`) prefix formats — normalize as
needed to locate the services repo.

---

## Step 2 — Discover IOC folders

List all subdirectories under `<services-repo>/services/` that contain
`config/ioc.yaml`. These are the converted IOCs to check.

```bash
find <services-repo>/services -maxdepth 2 -name ioc.yaml -path '*/config/*' \
  | sed 's|/config/ioc.yaml||' | sort
```

List the IOCs found and their count.

---

## Step 3 — Find matching XMLs

For each IOC folder, find the corresponding builder XML. The folder name is
the lowercase IOC stem — convert to uppercase to find the XML:

`bl19i-mo-ioc-03` → `BL19I-MO-IOC-03.xml`

Use [find-ioc-xmls.md](../shared/find-ioc-xmls.md) to locate the BUILDER
module for the beamline, then match each IOC stem to its XML file.

If an IOC folder has no matching XML (e.g. infrastructure IOCs not from
XMLbuilder), note it and skip.

---

## Step 4 — Parallel ioc-check

For each IOC with a matching XML, spawn a `general-purpose` subagent:

> Read `/workspaces/builder2ibek/.claude/skills/ioc-check/SKILL.md` and
> follow its instructions to check:
>
> XML: `<full-path-to-xml>`
> Services repo: `<resolved-services-repo>`
>
> Report your results when complete.

Run 3–5 IOCs in parallel for throughput. Each subagent creates its own
`EPICS_ROOT` so there are no file conflicts.

---

## Step 5 — Consolidate report

After all checks complete, report:

1. **Total IOCs** — number discovered in services repo
2. **Checked** — number with matching XMLs that were checked
3. **Skipped** — IOCs without matching XMLs (list them)
4. **generate2 results** — how many passed, how many failed (with error categories)
5. **st.cmd comparison** — IOCs with unexpected missing commands
6. **ioc.subst validation** — IOCs with macro concerns or db-compare issues
7. **No files changed** — confirm this skill made no modifications
