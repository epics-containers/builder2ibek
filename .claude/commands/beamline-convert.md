---
argument-hint: <beamline-prefix> [<path/to/services-repo>]
description: Convert all builder XML IOCs for a beamline to ibek ioc.yaml.
---

# Beamline Convert Workflow

Convert all builder XML IOCs for beamline `$1` (e.g. `BL19I`) to ibek
`ioc.yaml` in the services repo `$2`.

`builder2ibek beamline2yaml` does the deterministic part: it finds the XMLs,
plans each IOC's folder, picks its generic IOC image, writes the folders,
runs xml2yaml and schema-checks each `ioc.yaml`. This command adds the
judgement around it: what to do about blocked IOCs and missing modules, and
an `/ioc-convert` review of each converted IOC.

Never start an IOC to test it (see CLAUDE.md).

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../skills/shared/services-repo-resolution.md)
using `$2` (if provided) or the beamline prefix `$1`.

## Step 2 — Plan (dry run)

```bash
GITHUB_TOKEN=$(gh auth token) \
GITLAB_TOKEN=$(glab config get token --host gitlab.diamond.ac.uk) \
uv run builder2ibek beamline2yaml $1 --services-repo <services-repo> --json \
  > /tmp/$1-plan.json
```

This writes nothing. `GITHUB_TOKEN` avoids the GitHub release API rate limit;
`GITLAB_TOKEN` reads GitLab generic IOCs such as ioc-dlslinuxvac. Without
`--json` it prints the same plan as a table.

Read the plan:

- **failed steps** (`failures`): a pattern library, GitHub or GitLab lookup
  that failed, or a leftover `.<ioc>.beamline2yaml-backup` folder from an
  interrupted run. `--apply` writes nothing until there are none: fix the
  cause (tokens, network, move the backup back) and plan again.
- **actions**: `add`, `replace` (a dev-c7 legacy folder), `fastcs` (a
  dedicated PandA IOC), `skip` (an ibek folder: use `/beamline-reconvert`;
  a fastcs instance), `error` (the XML does not convert), and `blocked`.
- **blocked** IOCs, with the reason: a non-Linux target (Windows, vxWorks,
  RTEMS), no generic IOC image that builds them, or unresolved modules. A
  blocked IOC gets no folder and keeps its dev-c7 one.
- **modules** per IOC (pattern, build-time, unresolved), the runtime
  patterns, and the warnings, including entities dropped for manual review.

Show the user the plan: what will be written, what is blocked and why. Ask
which IOCs to convert (default: all that are not blocked); pass the rest as
`--only` in Step 4.

## Step 3 — Missing modules

For the modules the plan reports unresolved, or that keep an IOC blocked for
want of an image:

1. Read [module-special-cases.md](../skills/shared/module-special-cases.md):
   some modules need no support YAML, are replaced, or won't convert.
2. For each module with **no folder in either submodule**, follow
   [new-module-folder.md](../skills/shared/new-module-folder.md) and ask the
   user, one AskUserQuestion per module, naming every IOC that uses it. Drop
   the modules the user says not to create, and list their IOCs in the report.
3. Launch **one support-create subagent per remaining module** (all in
   parallel):

> Read `/workspaces/builder2ibek/.claude/commands/support-create.md` and
> follow its instructions to create a support YAML for the following module.
>
> Module name: `<module>`
> Known path from _RELEASE: `<resolved-path>`
> Entity types used across IOCs: [list]
> New folder: `<the user's answer: "create in ibek-support from <upstream>"
> or "create in ibek-support-dls">`, or "none: the folder exists". Without an
> answer from the user here, don't create a folder: stop and report back.

4. After all complete, run `./update-schema` once.

A new support YAML does not put the module into a generic IOC image: an IOC
stays blocked until an image in `GENERIC_IMAGES`
(`src/builder2ibek/beamline2yaml.py`) builds it. Report which generic IOC
would need the module; never add a beamline module to one (see CLAUDE.md).

## Step 4 — Apply

```bash
GITHUB_TOKEN=$(gh auth token) \
GITLAB_TOKEN=$(glab config get token --host gitlab.diamond.ac.uk) \
uv run builder2ibek beamline2yaml $1 --services-repo <services-repo> --apply \
  [--only <ioc-name> ...] [--descriptions-json <file>]
```

It writes the planned folders from `.ioc_template`, runs xml2yaml with the
chosen image (which adds the runtime patterns and sets the image in
`values.yaml`), and schema-checks each `ioc.yaml` with `ibek runtime
generate2` in a temporary EPICS_ROOT, with the support YAMLs of the patterns
the image installs. If an IOC's conversion fails or a pattern cannot be added,
its status is `error`: its new folder is removed and a replaced legacy folder
is put back, while a fastcs instance is left as written. An IOC that fails the
schema check keeps its folder, with the `ioc.yaml` to fix, and the validator's
output is in the report (`schema_error` with `--json`). The services repo is a git repo: `git status` shows what a run
wrote, and `git checkout`/`git clean` revert it.
Exit codes: 0 clean, 1 a failed plan step (nothing written), 2 conversion
errors, 3 schema check failures. `schema ok` means the `ioc.yaml` matches the
schema, not that the IOC can be deployed.

## Step 5 — Review each converted IOC

For each IOC with status `ok`, spawn a `general-purpose` subagent, up to
**10 in parallel** per batch, waiting for each batch before the next:

> Read `/workspaces/builder2ibek/.claude/commands/ioc-convert.md` and
> follow its instructions to review and fix the conversion of:
>
> XML: `<full-path-to-xml>`
> Services repo: `<resolved-services-repo>`
>
> beamline2yaml has already written `services/<ioc>/` from `.ioc_template`,
> set its image and run xml2yaml: don't recreate the folder or change the
> image. Do the converter review loop, the generate2 check against the
> original boot script, and the fixes. Create an EPICS_ROOT of your own
> (`export EPICS_ROOT=$(mktemp -d) && ./update-schema`). Don't create a new
> module folder in `ibek-support-dls/` or `ibek-support/`: if one is needed,
> report the module and the
> `/workspaces/builder2ibek/.claude/skills/shared/new-module-folder.md`
> findings back instead. Never start an IOC.
>
> Report your results when complete.

Skip the `fastcs` IOCs: beamline2yaml already wrote their fastcs-pandablocks
instances. List them in the report.

## Step 6 — Verify shared files after subagent completion

Parallel subagents can revert each other's edits to shared files (support
YAMLs, converters, skill docs). After each batch completes:

1. Check that shared files modified during earlier steps still contain the
   expected content (e.g. `type: object` not reverted to `type: str`).
2. Re-apply any fixes that were overwritten by a later subagent.

## Step 7 — Consolidate and report

1. List the IOCs converted, blocked (with reasons), skipped and in error, and
   the fastcs-pandablocks instances written for PandA IOCs
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
