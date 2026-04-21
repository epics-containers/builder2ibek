---
argument-hint: <module-name> [<module-path>]
description: Create or update ibek support YAML and install.yml for a single EPICS support module.
---

# Support YAML Creator

Create or update the ibek support YAML for module `$1`.

Before starting, read these reference documents:
- [support-yaml-rules.md](../skills/shared/support-yaml-rules.md) — rules for ibek support YAML
- [builder-py-analysis.md](../skills/shared/builder-py-analysis.md) — how to read builder.py

For deeper conceptual background, refer to
[ibek-concepts](../skills/ibek-concepts/SKILL.md) as needed.

---

## Input context

When spawned by an orchestrator (e.g. `/ioc-convert`), additional context may
be provided in the prompt:

- **Module name**: `$1` (always provided)
- **Known path from _RELEASE**: `$2` (optional — if provided, use it to find
  `etc/builder.py` and `db/` files directly)
- **Entity types needed**: list of `<module>.<Entity>` types used in the IOC
  (optional — if not provided, create entity models for all user-facing classes)
- **Sample parameter values**: from ioc.yaml entities (optional — helps verify
  types match)

---

## Step 1 — Check for existing support YAML

**Always check both submodules before creating anything:**
```bash
ls ibek-support-dls/$1/ ibek-support/$1/ 2>/dev/null
```

If a support YAML already exists, read it — you may only need to add missing
entity models, not create from scratch.

**Before creating anything**, read
[module-special-cases.md](../skills/shared/module-special-cases.md) and check whether
the module has non-standard naming or location.

## Step 2 — Locate the module

If `$2` (known path) is provided, use it directly.

Otherwise, follow [find-module-path.md](../skills/shared/find-module-path.md) or
discover the module version:
```bash
ls /dls_sw/prod/R3.14.12.7/support/$1/
```

## Step 3 — Read builder.py

Follow [builder-py-analysis.md](../skills/shared/builder-py-analysis.md) systematically.

Read all Python files in the module's `etc/` directory:
```bash
ls <module-path>/etc/*.py
```

For each user-facing class, extract:
- Class name and base type (`AutoSubstitution`, `Device`, etc.)
- Template file reference (`TemplateFile = '...'`)
- Parameters with types, defaults, and required/optional status
- `Initialise()` / `InitialiseOnce()` / `PostIocInitialise()` commands
- Dependencies and cross-references (`Ident` parameters)

## Step 4 — Read database files

For each `TemplateFile` referenced by a class:
```bash
grep "^# % macro" <module-path>/db/<file>.db
```

Match macros to parameters. Determine required vs optional.
Apply the **type inference rules** from
[ibek-concepts](../skills/ibek-concepts/SKILL.md).

## Step 5 — Determine DLS-specific vs community

**CRITICAL — no duplicates:** A module must exist in exactly ONE of the two
submodules. If step 1 found an existing folder in either location, always
use that same location. Never create a second copy in the other submodule.

- If the module is DLS-specific (no upstream open-source project):
  write to `ibek-support-dls/<module>/`
- If it could benefit other facilities (e.g. asyn, StreamDevice, motor):
  write to `ibek-support/<module>/`
- When uncertain, default to `ibek-support-dls/`

## Step 5b — Handle XML template entities

If a builder.py class inherits from `Xml` (or uses `XmlFile`), it is an **XML
template entity** — it expands an XML file into child entities from other
modules. These should **not** be expanded by a converter. Instead:

1. Read the XML template file (in `etc/makeIocs/<TemplateName>.xml`).
2. Create a support YAML entity model with:
   - **Parameters** matching only the macro arguments the XML template accepts
     (e.g. `dom`, `plc_ip`, `ts_ip`) — keep the ioc.yaml minimal.
   - **`sub_entities`** list: for each non-commented child element in the XML
     template, add an entry that references the existing entity type from the
     other module (e.g. `ether_ip.EtherIPInit`, `dlsPLC.NX102_vacValveDebounce`).
     Hardcoded values from the template become literals; macro references like
     `$(dom)` become `{{ dom }}` Jinja2 expressions.
   - **No `pre_init` / `post_init` / `databases`** — the sub_entities handle all
     init commands and db instantiation via their own entity definitions.
3. Do NOT create a converter for XML template entities.

Reference example: `ibek-support-dls/SR-VA/SR-VA.ibek.support.yaml` —
`d2PumpCart` entity using `sub_entities` to compose ether_ip, asyn, mks937a,
dlsPLC, and userIO entities.

## Step 6 — Write the support YAML

Create `<module>.ibek.support.yaml` following the rules in
[support-yaml-rules.md](../skills/shared/support-yaml-rules.md).

Use existing support YAMLs as templates:
- `ibek-support-dls/hidenRGA/` — standard module with multiple entity variants
- `ibek-support-dls/cmsIon/` — leaf entity (name dropped)
- `ibek-support/ffmpegServer/` — port-creating entity with `when: first`
- `ibek-support-dls/SR-VA/` — XML template entity using `sub_entities`

## Step 7 — Write the install.yml

Create `<module>.install.yml` with:
- DBD files (from `DbdFileList` in builder.py)
- Libraries (from `LibFileList`)
- Protocol files (from `ProtocolFiles`, using the source path within the repo)

Note: install files use `.yml` extension, not `.yaml`.

## Step 8 — Create converter if needed

Follow the `name` parameter rules in
[support-yaml-rules.md](../skills/shared/support-yaml-rules.md) to determine whether
`name` should be kept or dropped.

If `name` must be dropped (confirmed leaf entity), create or update
`src/builder2ibek/converters/<module>.py`. Follow the pattern in existing
converters like `src/builder2ibek/converters/cmsIon.py`. Converters are
auto-discovered — no registration needed.

**Important**: pass plain `dict` to `entity.add_entity()`, never `Entity(...)`.

## Step 9 — Validate

```bash
uv run pytest
```

Fix any failures before finishing.

Do **not** run `./update-schema` — the orchestrator handles that.

## Step 10 — Report

Return a summary of:
- Files created or modified (with paths)
- Entity models defined (list of `<module>.<Entity>` names)
- Any uncertainties (e.g. "could not find builder.py", "unclear pre_init")
- Whether a converter was created or modified (orchestrator needs to know
  whether to re-run `xml2yaml`)
