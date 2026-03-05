---
name: beamline-reconvert
description: Re-run xml2yaml on all IOCs for a beamline and validate with generate2 into a temp folder.
argument-hint: <beamline-prefix> [<path/to/services-repo>]
disable-model-invocation: true
---

# Beamline Reconvert Workflow

Re-convert all builder XML IOCs for beamline `$0` (e.g. `BL21I` or `i21`)
using the latest ibek-support definitions. This is a fast, single-agent
operation.

Use this after changing support YAMLs or converters to refresh all ioc.yaml
files in the services repo and validate them.

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../shared/services-repo-resolution.md)
using `$1` (if provided) or the beamline prefix `$0`.

---

## Step 2 — Discover all IOC XMLs

Normalize the beamline prefix `$0` to the full `BLXXY` form used in paths:
- `i21` → `BL21I`, `i19` → `BL19I`, `b07` → `BL07B`, etc.
- If `$0` is already in `BL…` form, use it directly.

The BUILDER module is at a **fixed, specific path**. Check work area first,
fall back to prod:

```bash
# Try work area first (most current):
ls /dls_sw/work/R3.14.12.7/support/BL21I-BUILDER/etc/makeIocs/*.xml 2>/dev/null

# If empty, fall back to prod (use latest version):
ls /dls_sw/prod/R3.14.12.7/support/BL21I-BUILDER/*/etc/makeIocs/*.xml 2>/dev/null
```

Replace `BL21I` with the actual normalized prefix.

**Do NOT search or `find` across `/dls_sw/`** — the path is deterministic
from the beamline prefix as shown above.

Filter out template XMLs (files containing `$(macro)` syntax) — these are not
standalone IOC definitions.

List all XMLs found with a count.

---

## Step 3 — Discover existing IOC folders

List all subdirectories under `<services-repo>/services/` that contain
`config/ioc.yaml`:

```bash
find <services-repo>/services -maxdepth 2 -name ioc.yaml -path '*/config/*' \
  | sed 's|/config/ioc.yaml||' | sort
```

Match each XML to its services folder (XML stem uppercase = folder name
lowercase). Only reconvert IOCs that have an existing folder with
`config/ioc.yaml` — skip XMLs with no matching services folder (they haven't
been converted yet).

Report any XMLs being skipped and why.

---

## Step 4 — Reconvert all IOCs

For each matched IOC, run:

```bash
uv run builder2ibek xml2yaml <path/to/IOC.xml> --yaml <services-repo>/services/<ioc-name>/config/ioc.yaml
```

Run these sequentially (they're fast). Capture and report any conversion
errors. Continue with the remaining IOCs if one fails.

---

## Step 5 — Schema-validate with generate2

Create a temporary `EPICS_ROOT` and set up ibek definitions:

```bash
export EPICS_ROOT=$(mktemp -d /tmp/epics-reconvert-XXXXXX)
./update-schema
```

`ibek runtime generate2` requires a **config directory** (not a file) that
contains `ioc.yaml`. Create a temp config dir, copy each ioc.yaml into it,
and run generate2:

```bash
TMPCONFIG=$(mktemp -d /tmp/reconvert-config-XXXXXX)

for ioc_yaml in <services-repo>/services/*/config/ioc.yaml; do
  ioc_name=$(basename $(dirname $(dirname "$ioc_yaml")))
  cp "$ioc_yaml" "$TMPCONFIG/ioc.yaml"
  echo "--- Validating $ioc_name ---"
  ibek runtime generate2 --no-pvi "$TMPCONFIG" 2>&1 || true
done

rm -rf "$TMPCONFIG" "$EPICS_ROOT"
```

Only loop over the IOCs that were reconverted in Step 4 (not all services
folders). The generated runtime output goes to `$EPICS_ROOT` and is
discarded — only the schema validation matters.

Report all validation/generation errors grouped by IOC. Continue with the
remaining IOCs if one fails.

---

## Step 6 — Report

Summarize:

1. **Reconverted** — number of IOCs reconverted successfully
2. **Skipped** — XMLs with no matching services folder
3. **Conversion errors** — IOCs where xml2yaml failed (with error messages)
4. **Validation** — pass/fail count per IOC, details of any generate2 failures
5. **Files changed** — run `git -C <services-repo> diff --stat` to show what
   changed

Do not commit anything. Suggest git commands:

```bash
git -C <services-repo> add services/
git -C <services-repo> commit -m "Reconvert IOCs with latest ibek-support"
```
