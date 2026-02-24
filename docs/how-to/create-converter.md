# How-to: Create a builder2ibek converter for a support module

When `builder2ibek xml2yaml` converts a builder XML file it applies a
**converter** — a small Python module — for each XML component prefix it
encounters.  If no converter exists, the entity is passed through unchanged
with whatever attributes the XML had.

This how-to explains when and how to write a new converter.

---

## Why fix builder2ibek rather than editing ioc.yaml by hand

It is tempting to run `xml2yaml`, fix up the resulting `ioc.yaml` manually,
and move on.  Resist this.  Writing a converter instead has important
advantages:

- **Others benefit immediately.** Anyone converting the same module gets
  correct output without knowing about the quirk.
- **Re-conversion is safe.** If the original builder XML is modified (a
  device address changes, a new instance is added) you can re-run `xml2yaml`
  and get a correct result.  Manual edits to `ioc.yaml` would have to be
  re-applied by hand.
- **The fix is tested.** Once you add a sample XML/YAML pair to
  `tests/samples/` the CI suite catches any future regressions.
- **The knowledge is captured.** The converter documents exactly what
  builder.py was doing implicitly, in executable form.

The rule of thumb: if you find yourself editing `ioc.yaml` to fix something
that came from `xml2yaml`, ask yourself whether that fix belongs in a
converter instead.

---

## When a converter is needed

A converter is needed when the ibek entity requires different field names,
values, or structure from the raw XML attributes.  Common cases:

| Situation | Converter action |
|---|---|
| An XML attribute has been renamed in ibek | `entity.rename("old", "new")` |
| An XML attribute is GUI-only or builder-only and absent from ibek | `entity.remove("attr")` |
| An XML string `"True"` / `"False"` should be a YAML boolean | Already handled by `@globalHandler`; check first |
| A numeric value must be transformed (e.g. `valve × 10 = addr`) | Arithmetic on `entity.addr` |
| The entity type itself must change (module renamed in ibek) | `entity.type = "newModule.NewClass"` |
| An XML element maps to a different ibek module entirely | `entity.type = "dlsPLC.something"` |
| One XML element should be deleted (e.g. replaced by an ibek default) | `entity.delete_me()` |
| One XML element should expand to two ibek entities | `entity.add_entity(Entity({...}))` |

---

## Converter anatomy

Every converter is a `.py` file in `src/builder2ibek/converters/`.
`moduleinfos.py` discovers them automatically at import time — no
registration step is needed.

The minimal structure is:

```python
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

# Must match the XML element prefix: <myModule.SomeClass .../>
xml_component = "myModule"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """Convert myModule XML entities to ibek YAML."""

    if entity_type == "SomeClass":
        entity.rename("oldParam", "newParam")
        entity.remove("builderOnlyParam")
```

### Required module-level names

| Name | Type | Purpose |
|---|---|---|
| `xml_component` | `str` or `list[str]` | XML prefix(es) this converter handles |
| `handler` | callable | Called once per matching entity during conversion |

### Optional module-level names

| Name | Type | Purpose |
|---|---|---|
| `yaml_component` | `str` | Override the ibek module prefix in the output (if different from `xml_component`) |
| `defaults` | `dict` | Default parameter values injected for specific entity types |
| `schema` | `str` | URL of the ibek IOC schema for the Generic IOC (informational) |

### The `@globalHandler` decorator

`@globalHandler` wraps your `handler` function so that the global
pre-processing runs first.  The global handler:

- Removes `gda_name` and `gda_desc` from every entity
- Converts string values `"True"` / `"False"` / `""` to Python
  `True` / `False` / `None`

Always use `@globalHandler` unless you have a specific reason not to.

---

## The `Entity` API

`Entity` is a `dict` subclass that also supports attribute-style access.
All XML attributes arrive as string values; the global handler has already
converted booleans and empty strings.

```python
entity.rename("old", "new")   # rename a key; no-op if absent
entity.remove("key")          # delete a key; no-op if absent
entity.type = "mod.Class"     # change the ibek entity type
entity.delete_me()            # mark this entity for removal from output
entity.add_entity(new)        # insert an extra entity after this one
```

Read-only access to the IOC-level context:

```python
ioc.ioc_name    # IOC name string
ioc.entities    # list of all entity dicts already processed
```

---

## Example 1: simple field rename and removal

The `autosave` XML element has several DLS-specific attributes that do not
exist in the ibek entity model:

```xml
<autosave.Autosave iocName="BL11I-CS-IOC-09" bl="True"
    path="/dls_sw/i11/epics/autosave" skip_1="True" name="AS"/>
```

The ibek model uses `P` for the PV prefix (derived from `iocName` with a
trailing colon added):

```python
# src/builder2ibek/converters/autosave.py
xml_component = "autosave"

@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "Autosave":
        entity.rename("iocName", "P")   # rename the field
        entity.P += ":"                 # append the colon
        entity.remove("bl")             # DLS-only flags not in ibek model
        entity.remove("name")
        entity.remove("path")
        entity.remove("skip_1")
        entity.debug = bool(entity.debug)
```

---

## Example 2: type change and value transformation

`vacuumValve.vacuumValve` maps to `dlsPLC.vacValve` with the `valve` number
multiplied by 10 to get `addr`, and the `crate` short name looked up to
obtain the full `vlvcc` PV device name:

```python
# src/builder2ibek/converters/vacuumValve.py
xml_component = "vacuumValve"
read100Objects = {}   # shared state to resolve crate name → port

@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "vacuumValveRead":
        read100Objects[entity.name] = entity.port
        entity.type = "dlsPLC.read100"
        entity.century = 0
        entity.remove("name")

    elif entity_type in ["vacuumValve", "vacuumValve_callback"]:
        entity.type = "dlsPLC.vacValve"
        entity.rename("crate", "vlvcc")
        entity.addr = int(entity.valve) * 10
        entity.remove("valve")
        entity.port = read100Objects[entity.vlvcc]
```

Note the module-level `read100Objects` dict: entities are processed in XML
document order, so a `vacuumValveRead` entity always appears before any
`vacuumValve` that references it.

---

## Example 3: deleting an entity

`devIocStats.devIocStatsHelper` is superseded by an ibek default that
auto-generates the equivalent entity.  The converter simply removes it:

```python
@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "devIocStatsHelper":
        entity.delete_me()
        return
```

---

## Example 4: handling multiple XML prefixes

One converter can handle several XML prefixes by setting `xml_component` to
a list.  This is useful for support modules that were renamed:

```python
xml_component = ["vacuumValve", "oldVacuum"]

@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    ...
```

---

## Adding a test

Once your converter produces correct output, add a sample XML and the
expected YAML to `tests/samples/` so the CI will catch regressions.

Use the provided helper script to regenerate all expected outputs:

```bash
cp MY-IOC.xml tests/samples/
cd tests/samples && ./make_samples.sh
```

Review the diff carefully — `make_samples.sh` overwrites the `.yaml` files
from the current converter output, so only commit when the output is correct.

The test suite runs all sample conversions automatically:

```bash
uv run pytest tests/test_file_conversion.py
```

---

## Submitting the converter

Converters are part of the `builder2ibek` source tree, not the
`ibek-support*` repositories.  Open a pull request against
[epics-containers/builder2ibek](https://github.com/epics-containers/builder2ibek)
including:

1. `src/builder2ibek/converters/<module>.py`
2. `tests/samples/<EXAMPLE>.xml` and `tests/samples/<example>.yaml`
