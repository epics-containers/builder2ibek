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
2. Check `<module>App/Db/*.substitutions` — identify runtime vs baked-in macros
3. ibek parameter names must match the XML attribute names exactly so
   `xml2yaml` round-trips correctly
4. `TemplateFile` → `databases[].file`
5. `PostIocInitialise` print statements → `post_init[].value`
6. `drvAsynIPPortConfigure` call → `pre_init[].value`
7. `STREAM_PROTOCOL_PATH` → `pre_init[]` with `when: first`
8. `DbdFileList` / `LibFileList` / `ProtocolFiles` → `install.yml`

Note: `install.yml` (not `.yaml`).

### 2. Create a Generic IOC repository

A Generic IOC bundles support modules into a container (Linux) or RTEMS binary.

Full guide: [docs/how-to/create-generic-ioc-repo.md](docs/how-to/create-generic-ioc-repo.md)

Quick reference:
- Use `copier copy gh:epics-containers/ioc-template ioc-<module>`
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
│   ├── installation.md
│   └── create-support-yaml.md   ← how to write ibek support YAML
├── how-to/
│   ├── create-generic-ioc-repo.md   ← ioc-template workflow
│   └── convert-ioc-instance.md      ← xml2yaml workflow with example
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
  instances of the same entity type are loaded. Used for `STREAM_PROTOCOL_PATH`
  and similar one-time environment setup.

**Runtime vs baked-in macros**
: Macros that appear in substitution pattern rows are expanded by MSI at build
  time and do not appear in the compiled `.db`. Only macros absent from all
  patterns (typically P, Q, PORT, BUFFER_SIZE) must be passed as
  `databases[].args`.

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
2. Register it in `src/builder2ibek/convert.py`
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
| `hidenRGA` | `ibek-support-dls/hidenRGA/` | 4 variants; baked-in MASS_RANGE |
| `cmsIon` | `ibek-support-dls/cmsIon/` | |
| `digitelMpc` | `ibek-support-dls/digitelMpc/` | |
| `iocStats` | `ibek-support/iocStats/` | community module |
| `StreamDevice` | `ibek-support/StreamDevice/` | community module |

The live IOC `bl-va-ioc-01` at
`/dls_sw/work/R7.0.7/ioc/BL/bl-va-ioc-01` is an example Generic RTEMS IOC
that uses `ibek-support-dls` (see its `AGENTS.md` for RTEMS-specific guidance).
