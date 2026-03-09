---
name: ibek-concepts
description: ibek entity model patterns — use when creating or editing support YAMLs, understanding type:id/object, databases.args, Jinja2 rendering, auto_* entities, or port reference patterns.
---

# ibek Entity Model Concepts

Reference for ibek support YAML patterns. Use this when writing or debugging
entity models in `*.ibek.support.yaml` files.

---

## ibek support YAML structure

`*.ibek.support.yaml` defines `entity_models`. Each model maps to a Python
class in the support module's `builder.py`.

`*.install.yml` declares DBDs, libraries, and protocol files for the Docker
build (`ansible.sh`).

---

## Jinja2 rendering

`pre_init`, `databases`, and `post_init` values are Jinja2 templates.
Entity parameters are the context: `{{P}}` resolves to parameter `P`.

---

## databases.args

`key: value` pairs passed as macros to `dbLoadRecords`.
- Omitting the value uses the parameter of the same name: `P:` → `P={{P}}`
- `.*:` passes ALL parameters through (correct for pure `AutoSubstitution` entities)

---

## when: first

A `pre_init` guard that runs a command only once per IOC, regardless of how
many instances are loaded. Maps to `InitialiseOnce` in builder.py.

---

## Database macros

Determined from `# % macro` declarations at the top of the compiled `.db` file
— never from `.subst` files.

- Macros **without** a default → required ibek parameters
- Macros **with** a default (e.g. `MASS_RANGE`) → optional ibek parameters
  (so instances can override)

---

## name parameter and type: id

Carry `name` through as `type: id` **only** when another entity cross-references
this one. The classic case is an asyn port creator (`asyn.AsynIP`) whose `name`
is the port identifier.

For leaf objects, **drop `name`** — the converter must call
`entity.remove("name")`. See `src/builder2ibek/converters/cmsIon.py`.

---

## PORT parameter and type: object (asyn port reference)

- Port-creating entity: `name` → `type: id`
- Referencing entity: `PORT` → `type: object`

In builder XML both share a matching string value; in ibek it becomes an
explicit, validated reference. Pass `PORT:` unchanged in `databases.args`.

See [create-support-yaml-advanced.md](../../../docs/tutorials/create-support-yaml-advanced.md).

---

## Auto-substitution entities (auto_*)

Entity types like `module.auto_xxxx` in builder XML correspond to
`xxxx.template` in `db/` of support module `module`.

Example: `mks937a.auto_mks937aInterlock` → `mks937aInterlock.template`

These need:
- Parameters + `databases` section only (no `pre_init`/`post_init`)
- `.*:` in `databases.args`
- Drop `name` (gui label, not a cross-reference)

---

## Parameter type inference from db templates

Do not default everything to `type: str`. Read the `.db`/`.template` and check
how each macro is used in EPICS record fields:

| Record field usage | ibek type |
|---|---|
| Numeric (DRVH, DRVL, HIGH, LOW, HOPR, LOPR, VAL on ao/ai/calc) | `float` |
| Integer (ADDR, channel, slot, NAXES, PLC, SREV, PREC) | `int` |
| String/PV (DESC, INP, OUT, PORT, device names) | `str` |

This matters because xml2yaml preserves YAML's native typing: `0.0001` becomes
float, `42` becomes int. Type mismatch → schema validation failure.

---

## Reference examples

| Module | Path | Notes |
|---|---|---|
| hidenRGA | `ibek-support-dls/hidenRGA/` | 4 variants; optional params with defaults |
| cmsIon | `ibek-support-dls/cmsIon/` | name dropped (leaf entity) |
| digitelMpc | `ibek-support-dls/digitelMpc/` | |
| iocStats | `ibek-support/iocStats/` | community module |
| StreamDevice | `ibek-support/StreamDevice/` | community module |

---

## Deeper docs

- [create-support-yaml.md](../../../docs/tutorials/create-support-yaml.md) — full tutorial
- [create-support-yaml-advanced.md](../../../docs/tutorials/create-support-yaml-advanced.md) — ports, templates
- [dlsplc-migration.md](../../../docs/reference/dlsplc-migration.md) — vacuumValve/interlock/temperature mapping
