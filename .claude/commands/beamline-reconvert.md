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
invoke `/support-fix`.

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
field), then schema-validates every reconverted ioc.yaml with
`ibek runtime generate2 --no-pvi` inside one EPICS_ROOT tempdir.

Flags: `--no-validate` skips the generate2 pass; `--only <ioc-name>`
(repeatable) limits the run.

Exit codes: `0` clean · `2` ≥1 `xml2yaml` error · `3` ≥1 `generate2`
failure · `1` hard failure. If the subcommand exits with code ≥ 4 or
emits no JSON, fall back to Appendix A. Do not silently skip validation.

---

## Step 3 — Report

Parse the JSON on stdout and summarise: reconverted count, skipped
(grouped by `reason`), each conversion error's message, validation
pass/fail counts with stderr tails for any failure. Then run
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
for ioc_yaml in <services-repo>/services/*/config/ioc.yaml; do
  cp "$ioc_yaml" "$TMPCONFIG/ioc.yaml"
  ibek runtime generate2 --no-pvi "$TMPCONFIG" 2>&1 || true
done
rm -rf "$TMPCONFIG" "$EPICS_ROOT"
```
