---
argument-hint: <beamline-prefix> [<path/to/services-repo>]
description: Re-run xml2yaml on all IOCs for a beamline and validate with generate2 into a temp folder.
---

# Beamline Reconvert Workflow

Re-convert all builder XML IOCs for beamline `$1` (e.g. `BL21I` or `i21`)
using the latest ibek-support definitions. Use this after changing support
YAMLs or converters.

`reconvert` runs `generate2` calls sequentially in a single EPICS_ROOT
tempdir; parallelisation is out of scope for this command.

If `xml2yaml` fails, fix the converter in `src/builder2ibek/converters/`
and re-run `reconvert`. If `generate2` fails, do NOT re-run `xml2yaml` —
invoke `/support-fix`. If a reconverted IOC uses a module with no folder in
either submodule, ask the user before creating one, following
[new-module-folder.md](../skills/shared/new-module-folder.md).

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../skills/shared/services-repo-resolution.md)
using `$2` (if provided) or the beamline prefix `$1`. Tell the user which
services repo is being used.

---

## Step 2 — Run the reconvert subcommand

```bash
uv run builder2ibek reconvert $1 --services-repo <services-repo> --json
```

Discovers BUILDER XMLs (work area first, prod fallback), matches lowercased
XML stems to `<services-repo>/services/<ioc-name>/config/ioc.yaml`,
re-runs `xml2yaml` for each match (preserving the existing `description`
field, and `--blgui` when the existing ioc.yaml has `BLGui.*` entities),
then schema-validates every reconverted ioc.yaml with
`ibek runtime generate2 --no-pvi` inside one EPICS_ROOT tempdir, together with
the support YAMLs of the runtime patterns in its `config/`. Each xml2yaml
adds the IOC's runtime patterns as `/ioc-convert` describes; report the
patterns added and any image set, from the notes.

Flags: `--no-validate` skips the generate2 pass; `--only <ioc-name>`
(repeatable) limits the run.

Exit codes: `0` clean · `2` ≥1 `xml2yaml` error · `3` ≥1 `generate2`
failure · `1` hard failure. If the subcommand exits with code ≥ 4 or
emits no JSON, fall back to Appendix A. Do not silently skip validation.

---

## Step 3 — Report

Parse the JSON on stdout and summarise: reconverted count, skipped
(grouped by `reason`), each conversion error's message, each entry in
`warnings` (won't-convert entities left out of an ioc.yaml, with the IOC,
entity type and reason), each entry in `fastcs` (fastcs-pandablocks
instances written for ADPandABlocks PandAs; a dedicated PandA IOC has
`status: fastcs` and no ioc.yaml to validate, see the `ADPandABlocks` section
of [module-special-cases.md](../skills/shared/module-special-cases.md)). A
PandA IOC with `status: refused` wrote nothing for its PandAs (another
instance serves them, or its folder serves different controllers), or is a
mixed IOC whose own folder is a fastcs instance: its old ioc.yaml is kept as it
was, it is not validated, and it must be resolved by hand using the refusal
warning, which names the folder that serves the PandA,
each entry in `notes` (what was written, kept or removed; anything needing
action is in `warnings`), validation pass/fail counts with stderr tails for
any failure. Then run
`git -C <services-repo> diff --stat` to show the file delta.

Do not commit anything. Suggest:

```bash
git -C <services-repo> add services/
git -C <services-repo> commit -m "Reconvert IOCs with latest ibek-support"
```

---

## Appendix A — Manual procedure (fallback)

```bash
# 1. Discover XMLs (work first, then prod — use <BLXXY> normalized form)
ls /dls_sw/work/R3.14.12.7/support/<BLXXY>-BUILDER/etc/makeIocs/*.xml \
  || ls /dls_sw/prod/R3.14.12.7/support/<BLXXY>-BUILDER/*/etc/makeIocs/*.xml

# 2. For each XML whose lowercased stem matches a services folder:
uv run builder2ibek xml2yaml <xml> --yaml <services-repo>/services/<ioc-name>/config/ioc.yaml

# 3. Schema-validate each one:
export EPICS_ROOT=$(mktemp -d /tmp/epics-reconvert-XXXXXX)
./update-schema
TMPCONFIG=$(mktemp -d /tmp/reconvert-config-XXXXXX)
# bash, not zsh: an unmatched glob must expand to nothing, not abort
bash -c '
for ioc_yaml in "$1"/services/*/config/ioc.yaml; do
  config=$(dirname "$ioc_yaml")
  find "$2" -mindepth 1 -delete
  find "$config" -maxdepth 1 \( -name ioc.yaml -o -name "*.ibek.support.yaml" \) \
    -exec cp {} "$2/" \;
  echo "== $ioc_yaml"
  ibek runtime generate2 --no-pvi "$2" 2>&1 || echo "FAILED: $ioc_yaml"
done' _ <services-repo> "$TMPCONFIG"
rm -rf "$TMPCONFIG" "$EPICS_ROOT"
```
