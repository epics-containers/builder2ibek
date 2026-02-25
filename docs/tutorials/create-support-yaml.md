# Creating ibek support YAML from a builder.py module

This tutorial walks you through converting a DLS EPICS support module that uses
the old XMLbuilder (`builder.py`) format into the ibek YAML files needed for a
Generic IOC. We use the `hidenRGA` support module as a concrete example.

After completing this tutorial you should understand:
- `ibek-support-dls/<module>/<module>.ibek.support.yaml` — entity model definitions
- `ibek-support-dls/<module>/<module>.install.yml` — build dependencies and assets

:::{important}
**This tutorial targets `ibek-support-dls`, the DLS-internal support
repository.**  If your module could be useful to other facilities, it is
strongly recommended to open-source it and contribute the support YAML to the
community `ibek-support` repository on GitHub instead.  The epics-containers
project provides a full tutorial for this approach, using the Lakeshore 340
temperature controller as an example:

[epics-containers: Creating a Generic IOC — Lakeshore 340](https://epics-containers.github.io/main/tutorials/generic_ioc.html#lakeshore-340-temperature-controller)

For a tutorial covering a more complex module and the full open-source
contribution workflow, see
[](create-support-yaml-advanced.md).
:::

## Steps

- Take a look at `etc/builder.py` in the support module you are converting
- Build a `<module>.install.yml` for it
- Build a `<module>.ibek.support.yaml` for it
- Convert any autosave comments in templates to `.req` files

---

## 1. Read builder.py

Find `etc/builder.py` in the module. Each Python class becomes one `entity_model`
in the support YAML.

For `hidenRGA` at `/dls_sw/prod/R3.14.12.7/support/hidenRGA/1-12/etc/builder.py`:

```python
from iocbuilder.modules.streamDevice import AutoProtocol
from iocbuilder import AutoSubstitution, Device
from iocbuilder.arginfo import *
from iocbuilder.modules.seq import Seq
from iocbuilder.modules.asyn import Asyn
from iocbuilder.modules.calc import Calc


class hidenRGA(AutoSubstitution, AutoProtocol, Device):
    '''Generic Hiden RGA module'''

    Dependencies = (Seq, Asyn, Calc)
    WarnMacros = False

    TemplateFile = 'hiden_generic.db'
    ProtocolFiles = ['hiden_rga.proto']
    LibFileList = ['hidenRGA']
    DbdFileList = ['hidenRGASupport', 'sncHidenRGA']

    def PostIocInitialise(self):
        print 'seq(sncDegas, "P=%s")' % self.args["P"]

class hidenRGA_hpr20(AutoSubstitution, AutoProtocol, Device):
    '''Hiden High Pressure Gas Analyser. Specialised for the Diamond High
    Pressure Sample Environment project.'''
    ...
    TemplateFile = 'hiden_hpr20.db'

class hidenRGA_qga(AutoSubstitution, AutoProtocol, Device):
    '''Hiden Quad Gas Analyser'''
    ...
    TemplateFile = 'hiden_qga.db'

class hidenRGA_HMT(AutoSubstitution, AutoProtocol, Device):
    '''Hiden HMT RC RGA module'''
    ...
    TemplateFile = 'hiden_HMT.db'
```

Key information extracted:

| Field | Value |
|---|---|
| Classes / entity models | `hidenRGA`, `hidenRGA_HMT`, `hidenRGA_hpr20`, `hidenRGA_qga` |
| Template files | `hiden_generic.db`, `hiden_HMT.db`, `hiden_hpr20.db`, `hiden_qga.db` |
| Lib | `hidenRGA` |
| DBDs | `hidenRGASupport`, `sncHidenRGA` |
| Protocol file | `hiden_rga.proto` |
| `PostIocInitialise` | `seq(sncDegas, "P=<P>")` |
| Dependencies | `Seq`, `Asyn`, `Calc` (implies asyn IP port is configured separately) |

---

## 2. Write the install.yml

The `.install.yml` (note: `.yml` not `.yaml`) captures build-time dependencies.

It provides instructions to ansible as to how to build this support module as part of
of a generic IOC container build.

Create `ibek-support-dls/hidenRGA/hidenRGA.install.yml`:

```yaml
# yaml-language-server: $schema=../../ibek-support/_scripts/support_install_variables.json

module: hidenRGA
version: 1-12

dbds:
  - hidenRGASupport.dbd
  - sncHidenRGA.dbd

libs:
  - hidenRGA

organization: https://gitlab.diamond.ac.uk/controls/support

protocol_files:
  - hidenRGAApp/protocol/hiden_rga.proto
```

Fields map directly from builder.py:
- `dbds` ← `DbdFileList`
- `libs` ← `LibFileList`
- `protocol_files` ← `ProtocolFiles` (use the source path within the repo)

---

## 3. Map builder arguments to ibek parameters

In builder XML, `hidenRGA_qga` appeared like this:

```xml
<hidenRGA.hidenRGA_qga BUFFER_SIZE="100" P="BL11I-EA-RGA-01" PORT="rgaPort" Q="" name="ENV.RGA"/>
```

The XML attributes become ibek parameter names.  `name` is dropped (the entity
has no cross-references and creates no asyn port) and handled by a converter.
`PORT` references the companion `asyn.AsynIP` entity by name.

| XML attribute | ibek parameter | type | notes |
|---|---|---|---|
| `name` | — | — | dropped; converter discards it from XML |
| `P` | `P` | `str` | PV prefix |
| `Q` | `Q` | `str` | PV suffix, default `""` |
| `PORT` | `PORT` | `object` | name of the companion `asyn.AsynIP` entity |
| `BUFFER_SIZE` | `BUFFER_SIZE` | `int` | default 1000 |

---

## 4. Determine the startup script sequence

The canonical source for `pre_init` and `post_init` content is **builder.py
itself**.  Look at the `Initialise`, `InitialiseOnce`, and `PostIocInitialise`
methods on each class — these are what builder emits into the boot script.

For `hidenRGA_qga` the relevant method is:

```python
def PostIocInitialise(self):
    print 'seq(sncDegas, "P=%s")' % self.args["P"]
```

This maps directly to the `post_init` block.  The `drvAsynIPPortConfigure` call
comes from the `Asyn` dependency rather than from the class itself, so it does
not appear in `hidenRGA_qga`'s own methods.

To see what the startup script should look like, see a boot script of a **real
IOC instance** that builder generated for a beamline using this module.  For
`hidenRGA_qga` the I11 IOC at
`/dls_sw/work/R3.14.12.7/support/BL11I-BUILDER/iocs/BL11I-CS-IOC-09/` was used;
its generated boot script contains:

```
drvAsynIPPortConfigure("ENV.RGA", "10.76.5.10:5025", 100, 0, 0)

epicsEnvSet "STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data"

dbLoadRecords("db/BL11I-CS-IOC-09_expanded.db", ...)

iocInit

seq(sncDegas, "P=BL11I-EA-RGA-01")
```

This can confirm the `pre_init`, `databases`, and `post_init` content needed.

Note that here drvAsynIPPortConfigure is supplied by an asyn.AsynIP object.

---

## 5. Write the ibek.support.yaml

`hidenRGA` has four builder.py classes (`hidenRGA`, `hidenRGA_hpr20`,
`hidenRGA_qga`, `hidenRGA_HMT`), each loading a different substitutions file
but otherwise identical in structure.  To keep the tutorial focused we work
through `hidenRGA_qga` in full detail — this is the variant deployed on I11 at
DLS.  The other three follow exactly the same logic and their entity models are
just repeats with the appropriate `db` filename substituted.

### 5a. Review what parameters you need

The XML element that appears in a real I11 IOC is:

```xml
<hidenRGA.hidenRGA_qga BUFFER_SIZE="100" P="BL11I-EA-RGA-01" PORT="rgaPort" Q="" name="ENV.RGA"/>
```

We derive the ibek parameters by investigating the purpose of each of the
attributes of the hidenRGA_qga element.

---

#### `name` → drop this parameter

**Source: XMLbuilder row identifier.**  *Some* XMLbuilder objects carry a `name`
attribute — not all do.  XMLbuilder uses it to auto-generate OPI/EDM GUI panels
(irrelevant in ibek) and to allow other objects to cross-reference this one.

You need to carry `name` through to ibek as a `type: id` parameter only when:

- another entity_model in a `support.yaml` will reference this entity. This
  is common for Asyn devices that expose their Asyn port as 'name', **or**
- you need the name as a runtime value inside the entity's own `pre_init` or
  `databases.args`.

The most common case is **any object that creates
an asyn port**.  The object calls `drvAsynIPPortConfigure` (or equivalent) with
`name` as the port identifier, and other objects reference it by that same port
name — so `name` identifies this object and provides a cross-reference target.
If you see a `drvAsynIPPortConfigure` or `drvAsynSerialPortConfigure` call in
`pre_init`, keep `name` as `type: id`.

If neither condition applies and this is a true *leaf* object, you can drop
`name` entirely — but then you need a converter to discard it when reading the
XML, so that `xml2yaml` does not try to pass an unrecognised attribute to the
entity model.  `src/builder2ibek/converters/cmsIon.py` is the simplest example:
it does nothing except call `entity.remove("name")` for its entity types.

For `hidenRGA_qga`, neither condition applies: the asyn port is created by the
companion `asyn.AsynIP` entity (not by this one), and nothing in `ioc.yaml`
cross-references `hidenRGA_qga` by name.  We therefore **drop** `name` and add
a converter that discards it when reading the XML.

---

#### `P` → `type: str`

**Source: database macro from  `hiden_qga.db`.**

The macro declarations at the top of
`/dls_sw/prod/R3.14.12.7/support/hidenRGA/1-12/db/hiden_qga.db` are the
definitive list of what must (or can) be passed at `dbLoadRecords` time:

```
# % macro, P, Prefix
# % macro, Q, Suffix
# % macro, PORT, Asyn port name
# % macro, MASS_RANGE, Mass range of RGA. Defaults to 100amu.
# % macro, HMT_RC, Set to one for high pressure HMT RC variant. Defaults to zero
```

Macros **without** a default in the declaration must always be supplied →
required ibek parameters.  Macros **with** a default (`MASS_RANGE`, `HMT_RC`)
may be omitted entirely from the call — which is why they did not need to appear
in the builder XML.  They can still be exposed as optional ibek parameters if
you want users to be able to override the default.

`P` has no default and therefore must always be supplied:

```
record(stringin, "$(P,undefined)$(Q,undefined):ID-I") { ... }
```

XML value: `P="BL11I-EA-RGA-01"`.

---

#### `Q` → `type: str`, `default: ""`

**Source: database macro, same reasoning as `P`.**

`Q` has no default in the `hiden_qga.db` macro declarations, however as the
one IOC we were translating used "", we give it the reasonable default of `""`
in the ibek model so it can be omitted from `ioc.yaml` when not needed.

XML value: `Q=""`.

---

#### `PORT` → `type: object` referencing the `asyn.AsynIP` entity

**Source: database macro in `hiden_qga.db`.**

`PORT` is declared in the `hiden_qga.db` header with no default and appears in
StreamDevice links:

```
record(stringin, "$(P,undefined)$(Q,undefined):ID-I")
{
    field(DTYP, "stream")
    field(INP,  "@hiden_rga.proto getID() $(PORT,undefined)")
```

It has no default, so it must be passed in `databases.args`.  In the builder XML, `PORT="rgaPort"` matched the `PORT`
attribute of the companion `<asyn.AsynIP PORT="rgaPort" .../>` element — i.e.
`PORT` is the *name of another entity*.

This is a very common ibek pattern: one entity creates an asyn port (an
`asyn.AsynIP` or `asyn.AsynSerial` entity with `name: type: id`), and a second
entity references it by name via a parameter called `PORT` (or sometimes
`ASYN_PORT`).  In ibek the referencing parameter has `type: object`, which
ensures `ioc.yaml` validation catches mismatched names.

XML value: `PORT="rgaPort"` → ibek parameter `PORT` of `type: object`, value is
the `name` of the `asyn.AsynIP` entity in `ioc.yaml`.

---

#### `BUFFER_SIZE` → `type: int`, `default: 1000`

**Source: database macro in `hiden_qga.db`.**

`hiden_qga.db` declares it as a macro and uses it in waveform records:

```
# % macro, BUFFER_SIZE, Number of points to allocate for results buffer
  field(NSAM, "$(BUFFER_SIZE,undefined)")
```

It has no meaningful default, so it must be passed in `databases.args`.

XML value: `BUFFER_SIZE="100"`.  The ibek default is set to 1000 — a
conservative value that works well for typical MID scan usage.

---

#### `MASS_RANGE` and `HMT_RC` → `type: int` with defaults from the `.db`

**Source: database macros with defaults in `hiden_qga.db`.**

```
# % macro, MASS_RANGE, Mass range of RGA. Defaults to 100amu.
# % macro, HMT_RC, Set to one for high pressure HMT RC variant. Defaults to zero
```

These were not present in the builder XML because their defaults were
sufficient for normal use.  We add them to the ibek entity model as optional
parameters with the same defaults, so that instances can override them if
needed.

Neither appears in the original XML — ibek defaults: `MASS_RANGE: 100`,
`HMT_RC: 0`.

---

### 5b. The entity model

Each entity model has four main sections:

- **`parameters:`** — the values a user supplies in `ioc.yaml`; ibek validates
  types
- **`pre_init:`** — IOC shell commands emitted before `iocInit`
- **`databases:`** — `.db` files to load via `dbLoadRecords`, with their macro
  arguments
- **`post_init:`** — IOC shell commands emitted after `iocInit`

The `pre_init`, `databases`, and `post_init` values are rendered as Jinja2
templates with the entity's parameters supplied as context, so `{{P}}` anywhere
in those sections resolves to the value of the `P` parameter.

`databases.args` is a list of `key: value` pairs passed as macros to
`dbLoadRecords`.  If the value is omitted (e.g. `P:` with no value), ibek
defaults it to the value of the parameter with the same name.  Keys can also be
regular expressions — `.*:` matches all parameters and passes them through,
which is convenient for pure `AutoSubstitution` entities where every parameter
maps directly to a database macro.


Create `ibek-support-dls/hidenRGA/hidenRGA.ibek.support.yaml`:

```yaml
# yaml-language-server: $schema=https://github.com/epics-containers/ibek/releases/download/3.1.1/ibek.support.schema.json

module: hidenRGA

entity_models:
  - name: hidenRGA_qga
    description: |-
      Hiden QGA Quad Gas Analyser, 200 amu, Faraday detector.
      Loads hiden_qga.db: global controls, bar scan (1-200 amu),
      MID scan (24 configurable mass channels), degas control,
      and per-mass sensitivity array.
    parameters:
      PORT:
        type: object
        description: |-
          Name of the asyn port to use for StreamDevice communication.
          Must be the name of a companion asyn.AsynIP entity.
      P:
        type: str
        description: |-
          PV prefix, e.g. "BL11I-EA-RGA-01". Macro passed to
          dbLoadRecords; present in the compiled .db as $(P).
      Q:
        type: str
        description: |-
          PV suffix appended to P in all PV names.
        default: ""
      BUFFER_SIZE:
        type: int
        description: |-
          Number of samples in the MID scan rolling results buffer per
          mass channel.
        default: 1000
      MASS_RANGE:
        type: int
        description: Mass range of RGA in amu.
        default: 100
      HMT_RC:
        type: int
        description: Set to 1 for high pressure HMT RC variant.
        default: 0

    databases:
      - file: $(HIDENRGA)/db/hiden_qga.db
        args:
          .*:

    post_init:
      - value: |
          seq(sncDegas, "P={{P}}{{Q}}")
```

The other three variants (`hidenRGA`, `hidenRGA_hpr20`, `hidenRGA_HMT`) have
identical parameters.  Add them as additional `entity_models` entries, changing
only the `name`, `description`, and the `databases[].file` path to the
appropriate `.db` file.

Because `name` was dropped from the entity model, a converter is needed to
discard it when reading the XML.  Create
`src/builder2ibek/converters/hidenRGA.py` following the pattern of
`src/builder2ibek/converters/cmsIon.py`:

```python
from builder2ibek.converters import register

@register("hidenRGA")
def convert(entity):
    entity.remove("name")
```

Register it in `src/builder2ibek/convert.py` alongside the other converters.

---

## 6. Verify with builder2ibek

Once your YAML is in `ibek-support-dls`, you can validate it by converting a
real IOC XML that uses the module:

```bash
uv run builder2ibek xml2yaml <path/to/IOC.xml> --yaml /tmp/test.yaml
```

Then inspect `/tmp/test.yaml` and check that the entity types and parameter names
match what you defined in the support YAML.

The real I11 IOC instance at
`/scratch/hgv27681/work/i11-services/services/b11i-ea-hiden-01/config/ioc.yaml`
was generated this way and illustrates the expected output:

```yaml
entities:
  - type: epics.EpicsEnvSet
    name: STREAM_PROTOCOL_PATH
    value: /epics/runtime/protocol/

  - type: asyn.AsynIP
    name: rgaPort
    port: 10.111.5.1:5025

  - type: hidenRGA.hidenRGA_qga
    BUFFER_SIZE: 100
    P: BL11I-EA-RGA-01
    PORT: rgaPort
```

Note the `STREAM_PROTOCOL_PATH` entry.  Rather than each StreamDevice entity
model emitting an `epicsEnvSet` in its own `pre_init`, ibek consolidates all
protocol files into a single directory (`/epics/runtime/protocol/`) during IOC
startup, and `builder2ibek` always adds a single `epics.EpicsEnvSet` entity for
`STREAM_PROTOCOL_PATH` to the generated `ioc.yaml`.  There is no need to handle
this in the support YAML at all.

Also note that `asyn.AsynIP` appears as a first-class entity in `ioc.yaml` with
its own `name: rgaPort`, and `hidenRGA_qga` references it via `PORT: rgaPort` —
the `type: object` pattern in action.

---

## Summary of what maps to what

| builder.py element | ibek YAML field |
|---|---|
| Class name | `entity_models[].name` |
| Docstring | `entity_models[].description` |
| `TemplateFile` | `databases[].file` |
| `DbdFileList` | `install.yml: dbds` |
| `LibFileList` | `install.yml: libs` |
| `ProtocolFiles` | `install.yml: protocol_files` |
| `PostIocInitialise` print statements | `post_init[].value` |
| Database macros without defaults (P, Q, PORT, BUFFER_SIZE) | `databases[].args` — required parameters |
| Database macros with defaults (MASS_RANGE, HMT_RC) | `databases[].args` — optional parameters with matching defaults |
| `Dependencies = (Asyn,...)` | `pre_init` `drvAsynIPPortConfigure` call |
| `Dependencies = (Seq,...)` | `post_init` `seq(...)` call |
| `when: first` | once-per-IOC commands (e.g. STREAM_PROTOCOL_PATH) |
