---
name: beamline-convert
description: Convert all builder XML IOCs for a beamline to ibek ioc.yaml.
argument-hint: <beamline-prefix> [<path/to/services-repo>]
disable-model-invocation: true
---

# Beamline Convert Workflow

Convert all builder XML IOCs for beamline `$0` (e.g. `BL19I`) to ibek
`ioc.yaml` in the services repo `$1`.

This skill orchestrates multiple `/ioc-convert` runs — one per IOC.

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../shared/services-repo-resolution.md)
using `$1` (if provided) or the beamline prefix `$0`.

## Step 2 — Discover all IOC XMLs

Follow [find-ioc-xmls.md](../shared/find-ioc-xmls.md) to find all IOC XML
files for beamline `$0`.

List all XMLs found. Ask the user to confirm which ones to convert (default:
all).

## Step 3 — Pre-pass: enumerate all modules

To avoid parallel write conflicts (two IOC subagents trying to create the same
support YAML), do a quick pre-pass:

1. Run `uv run builder2ibek xml2yaml` for each IOC to generate ioc.yaml files
2. Scan all generated ioc.yaml files for entity types
3. Deduplicate the list of modules needing support YAMLs across all IOCs
4. Launch **one support-create subagent per unique module** (all in parallel):

> Read `/workspaces/builder2ibek/.claude/skills/support-create/SKILL.md` and
> follow its instructions to create a support YAML for the following module.
>
> Module name: `<module>`
> Known path from _RELEASE: `<resolved-path>`
> Entity types used across IOCs: [list]

5. After all complete, run `./update-schema` once.

## Step 4 — Convert each IOC

For each IOC XML, spawn a `general-purpose` subagent:

> Read `/workspaces/builder2ibek/.claude/skills/ioc-convert/SKILL.md` and
> follow its instructions to convert:
>
> XML: `<full-path-to-xml>`
> Services repo: `<resolved-services-repo>`
>
> Note: support YAMLs for all modules have already been created in Step 3.
> Phase 2 (support YAML creation) should find them already present — only
> create entity models that are still missing.
>
> Report your results when complete.

**Parallelism**: each subagent creates its own `EPICS_ROOT` (Phase 0), so file
conflicts are avoided. Launch up to 10 IOCs in parallel per batch for best
throughput — wait for each batch to complete before launching the next.

## Step 5 — Consolidate and report

After all IOC conversions complete:

1. List which IOCs succeeded and which had issues
2. Run a final `./update-schema` and `uv run pytest` in the main repo
3. Report files changed across all repos
4. Suggest git commands for the user to review and commit:

```bash
# Services repo — all converted IOC instances:
git -C /workspaces/<beamline>-services add services/
git -C /workspaces/<beamline>-services commit -m "Add converted IOCs for <beamline>"

# builder2ibek — support YAMLs and converters:
git -C /workspaces/builder2ibek add ibek-support-dls/ ibek-support/
git -C /workspaces/builder2ibek add src/builder2ibek/converters/
git -C /workspaces/builder2ibek commit
```
