# builder2ibek

Converts DLS XMLbuilder EPICS IOC definitions to ibek YAML.

## Hard Rules

- Always use `uv run` — no system-wide installation.
- ibek parameter names must match XML attribute names exactly (round-trip requirement).
- `STREAM_PROTOCOL_PATH` is handled globally — do NOT add it to entity model `pre_init`.
- Install files are `*.install.yml` (not `.yaml`).
- Converters are auto-discovered from `src/builder2ibek/converters/*.py` — no registration needed.
- Find dependency init calls (e.g. `drvAsynIPPortConfigure`) in real boot scripts, not example ones.

## Services Repo

- If an existing IOC folder in a services repo has `dev-c7:` in its `values.yaml`, it is a legacy IOC. Delete the entire folder and recreate it from `.ioc_template` as usual.

## Foot-Guns

- Database macros come from the compiled `.db` file, never `.subst` files.
- `name` → `type: id` only when cross-referenced by another entity. Leaf entities must drop `name`. Beware untyped `object` params (e.g. `GAUGE`) that accept multiple entity types — check all callers. If you see `"Value error, object XXX not found in [...]"` during validation, you dropped an `id` that is still referenced.
- `auto_*` entities (`module.auto_xxxx`) → `xxxx.template` in `db/`. No `pre_init`/`post_init`.
- `entity.add_entity()` must receive plain `dict`, never `Entity(...)` (resets the extras list).

## Key Paths

| Path | Purpose |
|---|---|
| `/dls_sw/prod/R3.14.12.7/` | Default: released items, most-used EPICS version |
| `/dls_sw/prod/R7.0.7/` | RTEMS / latest EPICS |
| `/dls_sw/work/R3.14.12.7/` | Unreleased work (standard EPICS) |
| `ibek-support-dls/<module>/` | DLS entity models + install.yml |
| `ibek-support/<module>/` | Community entity models |
| `src/builder2ibek/converters/` | XML converters (one per module) |

Find IOC XMLs using a module:
```bash
grep -i <module> $(find /dls_sw/work/R3.14.12.7/support/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml")
```

## Testing

```bash
uv run pytest
./tests/samples/make_samples.sh   # regenerate sample outputs
./update-schema                   # rebuild global ioc schema
```

## On-Demand Knowledge

- `/support-inspect <module>` — analyze a support module's builder.py
- `/ioc-inspect <ioc-name>` — inspect an IOC's XML and support modules
- `/ioc-convert <xml> [services-repo]` — full conversion workflow with parallel subagents
- `/ioc-check <xml> [services-repo]` — validate a converted IOC's runtime assets
- Use `/ibek-concepts` for ibek entity model patterns (type: id/object, databases.args,
  Jinja2, when: first, auto_* entities, port references, database macros).
- See [docs/tutorials/create-support-yaml.md](docs/tutorials/create-support-yaml.md)
  and [docs/tutorials/create-support-yaml-advanced.md](docs/tutorials/create-support-yaml-advanced.md)
  for full support YAML guides.
- See [docs/reference/dlsplc-migration.md](docs/reference/dlsplc-migration.md)
  for vacuumValve/interlock/temperature migration details.
