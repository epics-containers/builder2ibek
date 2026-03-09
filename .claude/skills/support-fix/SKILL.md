---
name: support-fix
description: Fix support YAML or converter errors based on ibek generate2 error output.
argument-hint: <module-name>
disable-model-invocation: true
---

# Support YAML Error Fixer

Fix errors in the ibek support YAML (or converter) for module `$0` based on
`ibek runtime generate2` error output.

Before starting, read these reference documents:
- [support-yaml-rules.md](../shared/support-yaml-rules.md) — rules for ibek support YAML
- [error-categorization.md](../shared/error-categorization.md) — error diagnosis table

---

## Input context (provided by orchestrator)

The orchestrator provides in the prompt:
- **Module name**: which module's errors to fix
- **Known path from _RELEASE**: for finding `etc/builder.py` and `db/` files
- **Error messages**: verbatim output from `ibek runtime generate2`
- **Current support YAML content**: the existing YAML to fix
- **Relevant db files**: which db files to check for macro declarations

---

## Step 1 — Categorize errors

Read [error-categorization.md](../shared/error-categorization.md). For each
error, determine the fix type:

- **Support YAML only** — entity model needs a parameter added, type changed,
  or default added
- **Converter fix** — XML attribute needs transformation before ibek sees it
- **Both** — converter transforms the attribute AND support YAML needs updating

## Step 2 — Diagnose root cause

**For support YAML errors:**
- Read the current support YAML
- Read the relevant db file macros:
  ```bash
  grep "^# % macro" <module-path>/db/<file>.db
  ```
- Compare parameter names, types, and defaults against what generate2 expects
- Apply the type inference rules from
  [ibek-concepts](../ibek-concepts/SKILL.md)

**For converter errors:**
- Read the current converter (if any):
  `src/builder2ibek/converters/<module>.py`
- Determine what attribute transformation is needed

## Step 3 — Apply fixes

Follow the rules in [support-yaml-rules.md](../shared/support-yaml-rules.md)
when modifying the support YAML. For converter fixes, follow the pattern in
existing converters.

Key fix patterns:
- "Unknown parameter X" → add parameter to entity model (check db file for type)
- "Validation error" → fix parameter type (apply type inference rules)
- "object not found" → change id field to `type: id`
- "Field required" → add `default:` value
- "database arg not found" → add parameter or fix `databases.args`

**Important**: pass plain `dict` to `entity.add_entity()`, never `Entity(...)`.

## Step 4 — Validate

```bash
uv run pytest
```

Fix any regressions before finishing.

Do **not** run `./update-schema` or `xml2yaml` — the orchestrator handles
re-runs.

## Step 5 — Report

Return a summary of:
- What errors were fixed and how
- Whether a **converter fix** was also needed (orchestrator must re-run
  `xml2yaml` if so)
- Any errors that could not be resolved (with explanation)
