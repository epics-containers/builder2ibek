# ibek Support YAML Rules

Rules for creating and editing ibek support YAML files in the builder2ibek
conversion workflow. For deeper conceptual background on entity models, see
[ibek-concepts](../ibek-concepts/SKILL.md).

---

## Parameter naming

Parameter names in the ibek YAML **must** match XML attribute names exactly.
This is a round-trip requirement — `xml2yaml` generates entities using the
XML attribute names, and ibek validates them against the support YAML.

## Mapping builder.py to ibek YAML

| builder.py | ibek support YAML |
|---|---|
| `TemplateFile = 'foo.db'` | `databases[].file: $(<MODULE>)/db/foo.db` |
| `Initialise()` method | `pre_init` section |
| `InitialiseOnce()` method | `pre_init` with `when: first` |
| `PostIocInitialise()` method | `post_init` section |
| `AutoSubstitution` base class | `databases` section only (no init) |

## Jinja2 rendering

`pre_init`, `databases`, and `post_init` values are Jinja2 templates.
Entity parameters are available as context: `{{P}}` resolves to parameter `P`.

## databases.args

- `key: value` pairs passed as macros to `dbLoadRecords`
- Omitting the value uses the parameter of the same name: `P:` → `P={{P}}`
- `.*:` passes **all** entity parameters through (correct for pure
  `AutoSubstitution` entities — harmless extra macros are ignored by the db)

## name parameter

- **Default: keep `name: type: id`**. Only drop `name` after verifying it is
  truly a leaf (not cross-referenced by any entity in the module).
- **Verification step** — before dropping `name` from any entity, search ALL
  `type: object` params in the module's support YAML. Untyped `object` params
  (e.g. `GAUGE: type: object`) accept **any** entity with an id — check sample
  IOC YAML files to see which entity names actually appear as values. E.g.
  `mks937bRelays.GAUGE` accepts Gauge, Img, Pirg, and Cap entities, so all
  four need `name: type: id`.
- Only after confirming no `type: object` param references the entity should
  you drop `name` and add `entity.remove("name")` to the converter.
- Diagnostic: `"Value error, object XXX not found in [...]"` means you dropped
  an `id` that is still referenced — restore `type: id` on that entity

## PORT parameter

- `PORT` → `type: object` (asyn port reference pointing to the port creator)

## STREAM_PROTOCOL_PATH

Handled globally by the conversion framework — do **not** add
`STREAM_PROTOCOL_PATH` setup to any entity model's `pre_init`.

## Database macros — source of truth

- Always read macros from the **compiled `.db` file**, never from `.subst` files
- `grep "^# % macro" <module-path>/db/<file>.db` to list macros
- Macros without a default in the db → **required** ibek parameters
- Macros with a default (e.g. `$(NAME=value)`) → **optional** parameters with
  a `default:` value, so instances can override when needed

## Parameter type inference

Read the `.db`/`.template` file and check how each macro is used in EPICS
record fields. Do **not** default everything to `type: str`:

| EPICS field usage | ibek type |
|---|---|
| Numeric (DRVH, DRVL, DOL, HIGH, LOW, HOPR, LOPR, HIHI, LOLO, VAL on ao/ai/calc, EGU scaling) | `type: float` |
| Integer (SCAN index, ADDR, channel, slot, NAXES, PLC number, SREV, PREC) | `type: int` |
| String/PV (DESC, INP, OUT, PORT, device names) | `type: str` |

This matters because `xml2yaml` preserves YAML's native typing: `0.0001`
becomes a float, `42` becomes an int. If the support YAML declares `type: str`
but the ioc.yaml value is a float/int, schema validation fails.

## auto_* entities

- `module.auto_xxxx` in XML → `xxxx.template` in the module's `db/` directory
- Needs only `parameters` + `databases` section — **no** `pre_init`/`post_init`
- Use `.*:` in `databases.args` to pass all parameters through
- Drop `name` if present (it is a GUI label, not a cross-reference)
- Check `# % macro` lines in the template for required vs optional parameters

## File paths

| Type | Path |
|---|---|
| DLS-specific support YAML | `ibek-support-dls/<module>/<module>.ibek.support.yaml` |
| Community support YAML | `ibek-support/<module>/<module>.ibek.support.yaml` |
| Install file | `ibek-support-dls/<module>/<module>.install.yml` (`.yml` not `.yaml`) |

## Reference examples

Always look at existing support YAMLs before creating new ones:
- `ibek-support-dls/hidenRGA/` — 4 entity variants, optional params with defaults
- `ibek-support-dls/cmsIon/` — leaf entity with `name` dropped
- `ibek-support-dls/digitelMpc/` — port references and cross-entity dependencies

## Further reading

- [builder-py-analysis.md](builder-py-analysis.md) — systematic builder.py reading
- [create-support-yaml.md](../../../docs/tutorials/create-support-yaml.md) — tutorial
- [create-support-yaml-advanced.md](../../../docs/tutorials/create-support-yaml-advanced.md) — ports, templates, install.yml
