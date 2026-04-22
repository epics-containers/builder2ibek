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
| `TemplateFile = 'foo.db'` | `databases[].file: $(<MACRO>)/db/foo.db` |
| `Initialise()` method | `pre_init` section |
| `InitialiseOnce()` method | `pre_init` with `when: first` |
| `PostIocInitialise()` method | `post_init` section |
| `AutoSubstitution` base class | `databases` section only (no init) |

**`<MACRO>` is the module name with `-` replaced by `_` and then upper-cased**
— matches `macro: "{{ module | replace('-', '_') | upper }}"` in
`ibek-support/_ansible/roles/support/vars/main.yml`. Examples: `dlsPLC` →
`$(DLSPLC)`, `SR-VA` → `$(SR_VA)`, `Hy8401ip-asyn` → `$(HY8401IP_ASYN)`.
**Never** write `$(SR-VA)` — msi macro names forbid hyphens, so the ref is
left literal and msi dies with `No template file` at container startup.

## Jinja2 rendering, databases.args, name parameter, PORT parameter

See [ibek-concepts](../ibek-concepts/SKILL.md) for full details on these
topics. Key reminders:

- `name` → `type: id` only when cross-referenced. Drop for leaf entities.
  Diagnostic: `"Value error, object XXX not found"` = dropped an id still referenced.
- `PORT`, `port`, `MPC`, `controller`, or any `Ident("...", AsynPort/AsynIP/...)`
  parameter → `type: object` (asyn port reference). The parameter name varies by
  module — it is not always `PORT`. Always check the `ArgInfo` declaration in
  builder.py; if it uses `Ident(...)` it must be `type: object` in the support YAML.
- `.*:` in `databases.args` passes all parameters through.

## Globally-managed entities — don't re-add in entity models

The following are injected as defaults by `src/builder2ibek/convert.py` (or set
by the epics-containers runtime). Do **not** add them to any entity model's
`pre_init` or `sub_entities` — doing so causes duplicates or stale values:

| Entity / env var | Managed by |
|---|---|
| `devIocStats.iocAdminSoft` | `convert.py` default injection (filtered from XML by `deviocstats.py`) |
| `STREAM_PROTOCOL_PATH` | `convert.py` default injection (filtered from XML by `epics_base.py`) |
| `EPICS_TZ` | `convert.py` default injection |
| `IOCSH_PS1` (and any `IOCSH*`) | epics-containers runtime (filtered from XML by `epics_base.py`) |

If you find one of these in a `sub_entities:` list, delete it.

## Database macros, parameter types, auto_* entities

See [ibek-concepts](../ibek-concepts/SKILL.md) for full details. Key reminders:

- Read macros from compiled `.db` files, never `.subst`:
  `grep "^# % macro" <module-path>/db/<file>.db`
- Macros without defaults → required params; with defaults → optional params
- Infer `type: float`/`int`/`str` from EPICS record field usage (don't default
  to str — type mismatches cause schema validation failures)
- **Prefer fixing support YAML types over converter coercions:** when XML parses
  a numeric value (e.g. `0.5`) but the support YAML has `type: str`, change the
  support YAML param to `type: float` (or `int`) rather than adding a `str()`
  coercion in the converter. Only use `type: str` with converter coercion when
  the field genuinely needs to hold non-numeric values (e.g. VMAX default `$(VELO)`
  references another param). For optional numeric fields that can be absent, use
  `type: float` with no default, and emit a numeric default in the converter instead.
- `auto_*` entities need only `parameters` + `databases` (no init sections)

## File paths

| Type | Path |
|---|---|
| DLS-specific support YAML | `ibek-support-dls/<module>/<module>.ibek.support.yaml` |
| Community support YAML | `ibek-support/<module>/<module>.ibek.support.yaml` |
| Install file | `ibek-support-dls/<module>/<module>.install.yml` (`.yml` not `.yaml`) |

**No duplicates:** A module must exist in exactly ONE of `ibek-support/` or
`ibek-support-dls/`. Always check both directories before creating a new
folder. If the module already exists in one location, use that location —
never create a second copy in the other submodule.

## Reference examples

Always look at existing support YAMLs before creating new ones:
- `ibek-support-dls/hidenRGA/` — 4 entity variants, optional params with defaults
- `ibek-support-dls/cmsIon/` — leaf entity with `name` dropped
- `ibek-support-dls/digitelMpc/` — port references and cross-entity dependencies

## Further reading

- [builder-py-analysis.md](builder-py-analysis.md) — systematic builder.py reading
- [create-support-yaml.md](../../../docs/tutorials/create-support-yaml.md) — tutorial
- [create-support-yaml-advanced.md](../../../docs/tutorials/create-support-yaml-advanced.md) — ports, templates, install.yml
