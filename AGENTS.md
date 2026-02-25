# builder2ibek

## Purpose

`builder2ibek` converts DLS XMLbuilder EPICS IOC definitions to the ibek YAML
format used by epics-containers Generic IOCs.

The main command is:

```bash
uv run builder2ibek xml2yaml <IOC.xml> --yaml <output.yaml>
```

Always use `uv run` inside this repo — there is no system-wide installation.

---

## Three workflows

### 1. Add a new support module to ibek

When a builder.py module does not yet have ibek support YAML, you need to create:

```
ibek-support-dls/<module>/<module>.ibek.support.yaml
ibek-support-dls/<module>/<module>.install.yml
```

Full step-by-step guide: [docs/tutorials/create-support-yaml.md](docs/tutorials/create-support-yaml.md)

Quick reference:
1. Read `etc/builder.py` — each class → one `entity_model`
2. `DbdFileList` / `LibFileList` / `ProtocolFiles` → `install.yml`
3. ibek parameter names must match the XML attribute names exactly so
   `xml2yaml` round-trips correctly; `TemplateFile` → `databases[].file`
4. `PostIocInitialise`/`Initialise`/`InitialiseOnce` methods → `post_init`/`pre_init`.
   Calls contributed by dependencies (e.g. `drvAsynIPPortConfigure` from `Asyn`)
   won't appear in the class methods — find them in the boot script of a real
   builder-generated IOC, not an example boot script.
5. `STREAM_PROTOCOL_PATH` is handled globally by `builder2ibek` — do NOT add it
   to entity model `pre_init`. It is emitted as an `epics.EpicsEnvSet` entity in
   the generated `ioc.yaml` automatically.
6. For pure `AutoSubstitution` classes, use `.*:` in `databases.args` to pass
   all parameters through without listing each one.

Note: `install.yml` (not `.yaml`).

### 2. Create a Generic IOC repository

A Generic IOC bundles support modules into a container (Linux) or RTEMS binary.

Full guide: [docs/how-to/create-generic-ioc-repo.md](docs/how-to/create-generic-ioc-repo.md)

Quick reference:
- Use `uvx copier copy --trust gh:epics-containers/ioc-template ioc-<module>`
- Add `ibek-support-dls` as a submodule
- In the Dockerfile, `ansible.sh <module>` for each support module
- For RTEMS: use a native EPICS app instead; ibek-support submodules are
  present to pin versions but are not used by `make`

### 3. Convert an IOC XML instance

Convert an existing beamline builder XML into an ibek `ioc.yaml`:

Full guide: [docs/how-to/convert-ioc-instance.md](docs/how-to/convert-ioc-instance.md)

Quick reference:
```bash
uv run builder2ibek xml2yaml /path/to/BL-IOC.xml --yaml output.yaml
```
- Review output; commented XML elements are skipped
- Add XML to `tests/samples/` and run `make_samples.sh`
- Run `./update-schema` after adding new entity models

**dlsPLC migration**: `vacuumValve`, `interlock`, and `temperature` XML modules
are obsolete — `xml2yaml` auto-translates many to `dlsPLC.*` equivalents.
Some cases need manual fixup (vacuumValveRead2, pump templates, flow_asyn).
See [docs/reference/dlsplc-migration.md](docs/reference/dlsplc-migration.md)
for the full mapping table, argument transformations (valve×10=addr,
ilkA→ilk10, outaddr calculation), and which conversions are automatic.

---

## Repository layout

```
src/builder2ibek/
├── converters/      # one .py per support module — handles non-trivial mappings
├── convert.py       # orchestrates the xml2yaml conversion
├── types.py         # ibek entity type definitions
└── utils.py         # helpers

docs/
├── tutorials/
│   ├── convert-ioc-xml.md           ← quickstart: xml2yaml walkthrough
│   ├── create-support-yaml.md       ← how to write ibek support YAML
│   └── create-support-yaml-advanced.md ← advanced patterns (ports, templates)
├── how-to/
│   ├── create-generic-ioc-repo.md   ← ioc-template workflow
│   ├── convert-ioc-instance.md      ← xml2yaml workflow with example
│   └── verify-with-devcontainer.md  ← db-compare verification
├── explanations/
└── reference.md

tests/samples/       # XML + expected YAML pairs
ibek-support/        # submodule: community entity models
ibek-support-dls/    # submodule: DLS entity models
```

---

## Key concepts

**ibek support YAML** (`*.ibek.support.yaml`)
: Defines `entity_models` — the set of device types a support module provides.
  Each entity model has parameters, pre_init commands, databases to load, and
  post_init commands. Schema 3.1.1.

**install.yml** (`*.install.yml`)
: Declares the DBDs, libraries, and protocol files that `ansible.sh` will
  compile and install during the Docker build.

**`when: first`**
: A `pre_init` guard that ensures a command runs only once even when multiple
  instances of the same entity type are loaded. Used for one-time environment
  setup such as configuring a shared library path.

**Jinja2 rendering**
: `pre_init`, `databases`, and `post_init` values are rendered as Jinja2
  templates with the entity's parameters as context. `{{P}}` resolves to the
  value of the `P` parameter.

**`databases.args` conventions**
: A list of `key: value` pairs passed as macros to `dbLoadRecords`. If the
  value is omitted (e.g. `P:` with no value), ibek uses the value of the
  parameter with the same name. Keys can be regular expressions — `.*:` passes
  all parameters through, which is correct for pure `AutoSubstitution` entities.

**Database macros vs baked-in macros**
: The substitution (`.subst`) files are processed by MSI at build time to
  produce compiled `.db` files. Ibek loads these compiled `.db` files at
  runtime — you never need to look at the `.subst` files. The canonical source
  is the macro declarations at the top of the compiled `.db`. Macros listed
  there are database macros and must (or can) be passed in `databases[].args`.
  Macros with no default must always be supplied. Macros with a default
  (e.g. `MASS_RANGE`, `HMT_RC`) may not have appeared in the original builder
  XML but should still be added as optional ibek parameters with the same
  default, so instances can override them. Macros fully baked in by MSI will
  not appear in the `.db` declarations at all.

**`name` parameter and `type: id`**
: Only *some* XMLbuilder objects have a `name` attribute. Carry it through to
  ibek as `type: id` only when another entity will cross-reference this one, or
  when you need the name as a runtime value inside `pre_init`/`databases.args`.
  The most common case is any object that **creates an asyn port** (e.g.
  `asyn.AsynIP`, `asyn.AsynSerial`): its `name` becomes the port identifier, and
  other entities reference it by that name.  Keep `name` as `type: id` on the
  port-creating entity.
  If this is a leaf object with no referencing use, drop `name` — but a
  converter must call `entity.remove("name")` to discard it when reading the
  XML, so `xml2yaml` does not pass an unrecognised attribute to the entity model.
  See `src/builder2ibek/converters/cmsIon.py` as a minimal example.

**`PORT` parameter and `type: object` (asyn port reference pattern)**
: A very common ibek pattern: one entity creates an asyn port (its `name` is
  `type: id`), and a second entity references that port via a parameter named
  `PORT` (or `ASYN_PORT`) of `type: object`.  In the builder XML the two are
  linked by matching string values (e.g. `PORT="rgaPort"` on both elements).
  In ibek, `type: object` makes the link explicit and validated.  Pass `PORT:`
  through unchanged in `databases.args`.  Do not hard-code it or fold it into
  the port-creating entity.

**`builder2ibek xml2yaml`**
: Auto-generates `ioc.yaml` from builder XML. Converters in `converters/` handle
  module-specific remapping. Output should be reviewed and may need manual
  adjustment.

---

## Verifying a converted IOC (devcontainer + db-compare)

Full guide: [docs/how-to/verify-with-devcontainer.md](docs/how-to/verify-with-devcontainer.md)

Quick reference:
```bash
# 1. inside the Generic IOC devcontainer, point at your instance
ibek dev instance /workspaces/<project>/iocs/<ioc-name>

# 2. generate runtime assets (st.cmd + ioc.db) without launching the IOC
ibek runtime generate2 /epics/ioc/config

# 3. compare record-for-record against the original builder DB
uv run builder2ibek db-compare \
    /dls_sw/work/R3.14.12.7/support/BL11I-BUILDER/iocs/BL11I-CS-IOC-09/db/BL11I-CS-IOC-09_expanded.db \
    /epics/runtime/ioc.db \
    --output compare.diff
```

The output reports:
- Records in original but not in new (missing entity models or databases.args)
- Records in new but not in original (extra records, usually benign)
- Records present in both but with different field values

Use `--ignore "PATTERN"` to suppress known-acceptable differences.
Use `--remove-duplicates` if the original DB has duplicate record definitions.

To hot-reload a support module YAML without rebuilding the full container:
```bash
ibek dev support /epics/generic-source/ibek-support-dls/<module>
```

---

## Adding a new converter

If a module has no converter, its XML elements are passed through unchanged. To
add a converter:

1. Create `src/builder2ibek/converters/<module>.py`
2. No registration is needed — converters are auto-discovered by `moduleinfos.py` via glob scan of `src/builder2ibek/converters/*.py`
3. Add a sample XML to `tests/samples/` and run `make_samples.sh`
4. Commit both the converter and the generated YAML

---

## Testing

```bash
uv run pytest
./tests/samples/make_samples.sh   # regenerate all sample outputs
./update-schema                   # rebuild global ioc schema
```

The devcontainer (`.devcontainer/`) provides a full environment with
`ibek-support` and `ibek-support-dls` initialised, enabling schema validation
in VSCode.

---

## Reference examples

| Module | ibek support YAML | Notes |
|---|---|---|
| `hidenRGA` | `ibek-support-dls/hidenRGA/` | 4 variants; MASS_RANGE/HMT_RC optional with defaults |
| `cmsIon` | `ibek-support-dls/cmsIon/` | |
| `digitelMpc` | `ibek-support-dls/digitelMpc/` | |
| `iocStats` | `ibek-support/iocStats/` | community module |
| `StreamDevice` | `ibek-support/StreamDevice/` | community module |

The live IOC `bl-va-ioc-01` at
`/dls_sw/work/R7.0.7/ioc/BL/bl-va-ioc-01` is an example Generic RTEMS IOC
that uses `ibek-support-dls` (see its `AGENTS.md` for RTEMS-specific guidance).
