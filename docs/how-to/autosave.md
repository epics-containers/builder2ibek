# Generating autosave req files from DB templates

`builder2ibek autosave` reads DLS EPICS DB template files that contain
`# % autosave N` comments and writes the standard autosave `.req` files
needed by the EPICS autosave module in a Generic IOC.

## Background

DLS DB templates embed autosave hints as structured comments immediately
before `record(...)` declarations:

```
# % autosave 0 VAL
record(ao, "$(device):SETPOINT") { ... }
```

These comments were consumed at build time by the DLS `iocbuilder` toolchain.
When migrating a support module to an ibek Generic IOC the same information
must be expressed as standard autosave request files (`_positions.req` and
`_settings.req`).

`builder2ibek autosave` extracts all autosave hints from the template files
and writes those request files automatically.

---

## Autosave comment syntax

```
# % autosave <level> [<FIELD> ...]
record(<type>, "<PV_NAME>") { ... }
```

The comment applies to the **next** `record(...)` declaration in the file.

- **`<level>`** — `0`, `1`, or `2` (see level mapping below)
- **`<FIELD> ...`** — optional space-separated list of field names to save.
  If omitted, the entire record is saved (equivalent to writing the PV name
  without a field in the `.req` file).

A record can carry **multiple** autosave comments at different levels:

```
# % autosave 0 VAL
# % autosave 2 ZRST ONST TWST THST FRST FVST SXST SVST
record(mbbo, "$(device):$(loop_name):PID:SELECT") { ... }
```

---

## Level mapping

| DLS level | Meaning | Output file |
|---|---|---|
| `0` | Save on autosave pass 0 (restore on IOC start) | `<stem>_positions.req` |
| `1` | Save on pass 0 **and** pass 1 | `<stem>_settings.req` |
| `2` | Save on pass 1 only | `<stem>_settings.req` |

Levels 1 and 2 both map to `_settings.req` because AreaDetector and other
community modules use this convention, and the autosave documentation notes
that pass-1-only saves are rarely needed in practice.

---

## Running the command

```bash
uv run builder2ibek autosave <db_template> [<db_template> ...] --out-folder <path>
```

### Arguments

| Argument | Description |
|---|---|
| `DB_LIST...` | One or more DB template files (`.template`, `.db`) containing `# % autosave N` comments |
| `--out-folder PATH` | Directory to write `.req` files into (default: current directory) |

### Output files

For each input file `<name>.template` the command creates:

- `<name>_positions.req` — if any level-0 entries were found
- `<name>_settings.req` — if any level-1 or level-2 entries were found

---

## Example

### Input: `hiden_rga_sens_src.template`

```
# % autosave 2
record(ao, "$(P)$(Q):M$(M):SENS_SP") {
  ...
}
```

### Command

```bash
uv run builder2ibek autosave \
    hidenRGAApp/Db/hiden_rga_sens_src.template \
    --out-folder hidenRGAApp/Db/
```

### Output: `hiden_rga_sens_src_settings.req`

```
$(P)$(Q):M$(M):SENS_SP
```

(No `_positions.req` is written because there are no level-0 entries.)

---

### Example with field-level saves

#### Input: `eurothermLoopPIDselect.template` (excerpt)

```
# % autosave 0 VAL
record(ao, "$(device):$(loop_name):PID:SETVALUE1") { ... }

# % autosave 0 VAL
# % autosave 2 ZRST ONST TWST THST FRST FVST SXST SVST
record(mbbo, "$(device):$(loop_name):PID:SELECT") { ... }
```

#### Output: `eurothermLoopPIDselect_positions.req`

```
$(device):$(loop_name):PID:SETVALUE1.VAL
$(device):$(loop_name):PID:SELECT.VAL
```

#### Output: `eurothermLoopPIDselect_settings.req`

```
$(device):$(loop_name):PID:SELECT.ZRST
$(device):$(loop_name):PID:SELECT.ONST
$(device):$(loop_name):PID:SELECT.TWST
$(device):$(loop_name):PID:SELECT.THST
$(device):$(loop_name):PID:SELECT.FRST
$(device):$(loop_name):PID:SELECT.FVST
$(device):$(loop_name):PID:SELECT.SXST
$(device):$(loop_name):PID:SELECT.SVST
```

---

## Processing multiple templates at once

Pass all template files as positional arguments to generate all `.req` files
in one invocation:

```bash
uv run builder2ibek autosave \
    hidenRGAApp/Db/hiden_generic.db \
    hidenRGAApp/Db/hiden_rga_sens_src.template \
    hidenRGAApp/Db/hiden_rga_mid_mass.template \
    --out-folder hidenRGAApp/Db/
```

Or use shell globbing:

```bash
uv run builder2ibek autosave hidenRGAApp/Db/*.template --out-folder hidenRGAApp/Db/
```

---

## Where to place the generated files

Place the `.req` files alongside the DB templates inside the support module
source tree, typically in `<module>App/Db/`.  Commit them to version control
so that the Generic IOC Docker build includes them without needing to run
`builder2ibek autosave` at build time.

At runtime, ibek's `ibek runtime generate2` command scans all entities in
`ioc.yaml` and assembles the aggregate `autosave_positions.req` and
`autosave_settings.req` files in `/epics/runtime/`.  The `autosave.Autosave`
entity then loads these via `create_monitor_set` in the startup script:

```
# from autosave.ibek.support.yaml
set_requestfile_path("/epics", "runtime")
...
create_monitor_set autosave_positions.req, 5, ""
create_monitor_set autosave_settings.req, 30, ""
```

This means the per-module `.req` files generated by `builder2ibek autosave`
feed into the ibek runtime generation pipeline rather than being loaded
directly by the EPICS autosave module.

:::{tip}
If you are not using a DLS support module, but are switching to using the upstream
module and it has no .req files then you have two options:

1. add the req files as above and submit a PR to upstream (not always possible)
2. drop the generated req files into the ibek-support folder alongside
   xxx.ibek.support.yaml. These will be used at runtime by ibek startup.
:::

---

## Integration with the conversion workflow

If you are converting an existing DLS IOC support module to ibek, generate
the autosave request files as part of the initial migration:

1. [Create the ibek support YAML](../tutorials/create-support-yaml.md)
2. Run `builder2ibek autosave` on all DB templates that carry `# % autosave`
   comments
3. Commit the generated `.req` files into the support module's `Db/` directory
4. Add an `autosave.Autosave` entity to your `ioc.yaml` (this is usually
   already present in converted IOCs — see
   [Convert an IOC instance](convert-ioc-instance.md))
