# builder2ibek — Copilot Instructions

Converts DLS XMLbuilder EPICS IOC definitions to ibek YAML for epics-containers.

## MCP Tools Available

This project provides MCP tools via `mcp_server.py`. Use them to query the DLS
filesystem and analyze IOC/module structure:

- **find_module_path** — Resolve a support module's filesystem path (e.g. `hidenRGA` → `/dls_sw/prod/R3.14.12.7/support/hidenRGA/3-17`)
- **find_boot_script** — Get the original VxWorks boot script for an IOC
- **find_ioc_xmls** — List all IOC XMLs for a beamline (e.g. `BL19I`)
- **support_inspect** — Analyze a module's builder.py (classes, parameters, databases, st.cmd commands)
- **ioc_inspect** — Parse an IOC XML and report modules/entities used

## Key Paths

| Path | Purpose |
|---|---|
| `/dls_sw/prod/R3.14.12.7/` | Released support modules and IOCs |
| `/dls_sw/work/R3.14.12.7/` | Unreleased work area |
| `ibek-support-dls/<module>/` | DLS-internal entity models |
| `ibek-support/<module>/` | Community entity models |
| `src/builder2ibek/converters/` | XML converters (one per module, auto-discovered) |

## Converter Pattern

Each converter in `src/builder2ibek/converters/<module>.py`:
- Sets `xml_component` to match the XML namespace
- Has a `handler(entity, entity_type, ioc)` function decorated with `@globalHandler`
- Is auto-discovered — no registration needed

## Common Foot-Guns

- Database macros come from compiled `.db` files, never `.subst` files
- `name` → `type: id` only when cross-referenced by another entity. Leaf entities must drop `name`
- `STREAM_PROTOCOL_PATH` is handled globally — do NOT add it to entity model `pre_init`
- Install files use `.install.yml` extension (not `.yaml`)
- ibek parameter names must match XML attribute names exactly (round-trip requirement)

## Testing

```bash
uv run pytest                        # run all tests
./tests/samples/make_samples.sh      # regenerate sample outputs
./update-schema                      # rebuild global ioc schema
```

## Tutorials

- `docs/tutorials/create-support-yaml.md` — basic support YAML creation
- `docs/tutorials/create-support-yaml-advanced.md` — advanced patterns
- `docs/reference/dlsplc-migration.md` — vacuumValve/interlock/temperature migration
