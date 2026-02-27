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

## Searching /dls_sw

When looking up support modules, builder.py files, db files, or IOC instances
in `/dls_sw`, use these paths:

| Path | Purpose |
|---|---|
| `/dls_sw/prod/R3.14.12.7/` | Released items for the current most widely used EPICS version |
| `/dls_sw/prod/R7.0.7/` | Latest EPICS version, used especially for RTEMS IOCs |
| `/dls_sw/work/R3.14.12.7/` | Unreleased/in-progress work for the standard EPICS version |
| `/dls_sw/work/R7.0.7/` | Unreleased/in-progress RTEMS work (most likely to have recent changes) |

Default to `/dls_sw/prod/R3.14.12.7/` unless there is a specific reason to
look elsewhere (e.g. RTEMS, or seeking the latest unreleased changes).

To find builder XML files for IOCs that use a particular support module, use:

```bash
grep -i <module> $(find /dls_sw/work/R3.14.12.7/support/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml")
```

Example — find all IOCs using hidenRGA:
```bash
grep -i hidenRGA $(find /dls_sw/work/R3.14.12.7/support/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml")
```

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
: Defines `entity_models` — parameters, pre_init commands, databases to load,
  and post_init commands.  Full walkthrough:
  [docs/tutorials/create-support-yaml.md](docs/tutorials/create-support-yaml.md).

**install.yml** (`*.install.yml`)
: Declares the DBDs, libraries, and protocol files that `ansible.sh` will
  compile and install during the Docker build.

**Jinja2 rendering**
: `pre_init`, `databases`, and `post_init` values are Jinja2 templates with the
  entity's parameters as context. `{{P}}` resolves to the value of parameter `P`.

**`databases.args` conventions**
: `key: value` pairs passed as macros to `dbLoadRecords`. Omitting the value
  uses the parameter of the same name. `.*:` passes all parameters through
  (correct for pure `AutoSubstitution` entities).

**`when: first`**
: A `pre_init` guard that runs a command only once per IOC regardless of how
  many instances are loaded. Maps to `InitialiseOnce` in builder.py.

**Database macros**
: Determined from the macro declarations at the top of the compiled `.db` file —
  never from `.subst` files. Macros without a default must be ibek parameters;
  those with a default (e.g. `MASS_RANGE`) should be optional ibek parameters so
  instances can override them.

**`name` parameter and `type: id`**
: Carry `name` through as `type: id` only when another entity cross-references
  this one.  The classic case is an asyn port creator (`asyn.AsynIP` etc.) whose
  `name` is the port identifier.  For leaf objects, drop `name` — the converter
  must call `entity.remove("name")`.  See `src/builder2ibek/converters/cmsIon.py`.

**`PORT` parameter and `type: object` (asyn port reference pattern)**
: Port-creating entity: `name` → `type: id`.  Referencing entity: `PORT` →
  `type: object`.  In builder XML the two share a matching string value; in ibek
  it becomes an explicit, validated reference.  Pass `PORT:` unchanged in
  `databases.args`.  See
  [docs/tutorials/create-support-yaml-advanced.md](docs/tutorials/create-support-yaml-advanced.md).

**Auto-substitution entities (`auto_*`)**
: Entity types like `module.auto_xxxx` in builder XML correspond to a database
  template `xxxx.template` in the `db/` directory of support module `module`.
  For example, `mks937a.auto_mks937aInterlock` → `mks937aInterlock.template`
  in `mks937a/db/`. These need a support YAML entity model with parameters and
  a `databases` section only (no `pre_init`/`post_init`). Use `.*:` in
  `databases.args` and drop `name` (gui label, not a cross-reference).

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
