# Tutorial: Creating ibek support YAML from a builder.py module (DLS-internal)

This tutorial walks you through converting a DLS EPICS support module that uses
the old XMLbuilder (`builder.py`) format into the ibek YAML files needed for a
Generic IOC. We use the `hidenRGA` support module as a concrete example.

After completing this tutorial you will have created:
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

For a how-to covering the open-source workflow see
[Create open-source ibek support YAML](../how-to/create-opensource-support-yaml.md).
:::

## Prerequisites

- Access to the module source at its DLS prod or work path
- An `ibek-support-dls` repository (or submodule) to write the files into
- Familiarity with EPICS asyn/StreamDevice concepts

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

## 2. Determine runtime vs baked-in macros

`AutoSubstitution` classes derive their parameters from the template's
substitution file. Macros that appear **in the pattern rows** are expanded by MSI
at build time and do not survive into the compiled `.db`. Only macros **absent
from patterns** remain as `$(MACRO)` references at runtime.

For `hidenRGA` the relevant substitution file is
`hidenRGAApp/Db/hiden_qga.substitutions` (same logic applies to all four variants):

```
file hiden_rga_global.template
{
pattern {MASS_RANGE}
 {200}
}
...
file hiden_rga_mid_mass.template
{
pattern {NAME, ROW, MASS, MASS_RANGE, DETECTOR, VARIABLE, DWELL, SETTLE, EGU, PREC, ADEL, EGUCAL, ENABLE, DISP}
 {1, 1, 1, 200, 0, 0, 100, 10, Torr, 2, 1e-11, mbar, 1, 1}
 ...
}
```

`MASS_RANGE` appears in every pattern row — it is baked in.

The macros **not** present in any pattern row — `P`, `Q`, `PORT`, and
`BUFFER_SIZE` — survive as `$(P)`, `$(Q)`, `$(PORT)`, `$(BUFFER_SIZE)` in the
compiled `.db` and **must** be passed at `dbLoadRecords` time.

---

## 3. Map builder arguments to ibek parameters

In builder XML, `hidenRGA_qga` appeared like this:

```xml
<hidenRGA.hidenRGA_qga BUFFER_SIZE="100" P="BL11I-EA-RGA-01" PORT="rgaPort" Q="" name="ENV.RGA"/>
```

The XML attributes become ibek parameter names.  The asyn port (`PORT`) was
previously provided by a separate `<asyn.AsynIP>` element; in ibek we keep this
separation: the `name` parameter becomes the asyn port identifier, and `PORT` in
`databases.args` is set to `"{{name}}"`.

| XML attribute | ibek parameter | type | notes |
|---|---|---|---|
| `name` | `name` | `id` | asyn port name, unique per instance |
| `P` | `P` | `str` | PV prefix |
| `Q` | `Q` | `str` | PV suffix, default `""` |
| `PORT` | — | — | not a parameter; set to `{{name}}` in databases.args |
| `BUFFER_SIZE` | `BUFFER_SIZE` | `int` | default 1000 |

An additional `ip` parameter (str) is added to specify the network address — this
has no XML equivalent but is required for `drvAsynIPPortConfigure` in `pre_init`.

---

## 4. Check the example boot script

The compiled example at
`iocs/example/iocBoot/iocexample/O.linux-x86_64/stexample.boot` confirms the
runtime initialisation sequence:

```
drvAsynIPPortConfigure("rgaPort", "10.76.5.10:5025", 100, 0, 0)

epicsEnvSet "STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data"

dbLoadRecords 'db/example_expanded.db'

iocInit

seq(sncDegas, "P=hidenExample")
```

This gives us the exact `pre_init`, `databases`, and `post_init` content needed.

---

## 5. Write the install.yml

The `.install.yml` (note: `.yml` not `.yaml`) captures build-time dependencies.

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

## 6. Write the ibek.support.yaml

Create `ibek-support-dls/hidenRGA/hidenRGA.ibek.support.yaml`. Repeat an
`entity_model` block for every class in builder.py. The `when: first` guard on
the `STREAM_PROTOCOL_PATH` environment set ensures it only runs once even when
multiple hidenRGA instances are loaded.

```yaml
# yaml-language-server: $schema=https://github.com/epics-containers/ibek/releases/download/3.1.1/ibek.support.schema.json

module: hidenRGA

entity_models:
  - name: hidenRGA
    description: |-
      Hiden Analytical RGA (Residual Gas Analyser), generic variant, 100 amu.
      Loads hiden_generic.db which includes: global controls (state, filaments,
      PSU, LEDs, error handling), bar scan (1-100 amu), MID scan (24 channels,
      default masses 1-24 amu), degas control, and per-mass sensitivity array.
    parameters:
      name:
        type: id
        description: |-
          Unique name for this RGA instance, used as the asyn port name.
      ip:
        type: str
        description: |-
          IP address and TCP port of the Hiden HAL RC controller,
          e.g. "192.168.0.1:5025"
      P:
        type: str
        description: |-
          PV prefix, e.g. "BL01I-EA-RGA-01:"
      Q:
        type: str
        description: |-
          PV suffix. Defaults to empty string.
        default: ""
      BUFFER_SIZE:
        type: int
        description: |-
          Number of samples in the MID scan rolling results buffer per mass channel.
        default: 1000

    pre_init:
      - value: |
          drvAsynIPPortConfigure("{{name}}", "{{ip}}", 100, 0, 0)
      - when: first
        value: |
          epicsEnvSet("STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data")

    databases:
      - file: $(HIDENRGA)/db/hiden_generic.db
        args:
          P:
          Q:
          PORT: "{{name}}"
          BUFFER_SIZE:

    post_init:
      - value: |
          seq(sncDegas, "P={{P}}{{Q}}")

  - name: hidenRGA_HMT
    description: |-
      Hiden HMT RC RGA, high-pressure variant, 100 amu.
    parameters:
      name:
        type: id
        description: Unique name for this RGA instance, used as the asyn port name.
      ip:
        type: str
        description: IP address and TCP port of the Hiden HAL RC controller.
      P:
        type: str
        description: PV prefix.
      Q:
        type: str
        description: PV suffix.
        default: ""
      BUFFER_SIZE:
        type: int
        description: Rolling buffer size per mass channel.
        default: 1000

    pre_init:
      - value: |
          drvAsynIPPortConfigure("{{name}}", "{{ip}}", 100, 0, 0)
      - when: first
        value: |
          epicsEnvSet("STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data")

    databases:
      - file: $(HIDENRGA)/db/hiden_HMT.db
        args:
          P:
          Q:
          PORT: "{{name}}"
          BUFFER_SIZE:

    post_init:
      - value: |
          seq(sncDegas, "P={{P}}{{Q}}")

  - name: hidenRGA_hpr20
    description: |-
      Hiden HPR-20 High Pressure Gas Analyser, 200 amu, SEM detector.
    parameters:
      name:
        type: id
        description: Unique name for this RGA instance, used as the asyn port name.
      ip:
        type: str
        description: IP address and TCP port of the Hiden HAL RC controller.
      P:
        type: str
        description: PV prefix.
      Q:
        type: str
        description: PV suffix.
        default: ""
      BUFFER_SIZE:
        type: int
        description: Rolling buffer size per mass channel.
        default: 1000

    pre_init:
      - value: |
          drvAsynIPPortConfigure("{{name}}", "{{ip}}", 100, 0, 0)
      - when: first
        value: |
          epicsEnvSet("STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data")

    databases:
      - file: $(HIDENRGA)/db/hiden_hpr20.db
        args:
          P:
          Q:
          PORT: "{{name}}"
          BUFFER_SIZE:

    post_init:
      - value: |
          seq(sncDegas, "P={{P}}{{Q}}")

  - name: hidenRGA_qga
    description: |-
      Hiden QGA Quad Gas Analyser, 200 amu, Faraday detector.
    parameters:
      name:
        type: id
        description: Unique name for this RGA instance, used as the asyn port name.
      ip:
        type: str
        description: IP address and TCP port of the Hiden HAL RC controller.
      P:
        type: str
        description: PV prefix.
      Q:
        type: str
        description: PV suffix.
        default: ""
      BUFFER_SIZE:
        type: int
        description: Rolling buffer size per mass channel.
        default: 1000

    pre_init:
      - value: |
          drvAsynIPPortConfigure("{{name}}", "{{ip}}", 100, 0, 0)
      - when: first
        value: |
          epicsEnvSet("STREAM_PROTOCOL_PATH", "$(HIDENRGA)/data")

    databases:
      - file: $(HIDENRGA)/db/hiden_qga.db
        args:
          P:
          Q:
          PORT: "{{name}}"
          BUFFER_SIZE:

    post_init:
      - value: |
          seq(sncDegas, "P={{P}}{{Q}}")
```

---

## 7. Verify with builder2ibek

Once your YAML is in `ibek-support-dls`, you can validate it by converting a
real IOC XML that uses the module:

```bash
uv run builder2ibek xml2yaml <path/to/IOC.xml> --yaml /tmp/test.yaml
```

Then inspect `/tmp/test.yaml` and check that the entity types and parameter names
match what you defined in the support YAML.

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
| Runtime macros (P, Q, PORT, BUFFER_SIZE) | `databases[].args` |
| Baked-in macros (MASS_RANGE, HMT_RC) | not in databases.args |
| `Dependencies = (Asyn,...)` | `pre_init` `drvAsynIPPortConfigure` call |
| `Dependencies = (Seq,...)` | `post_init` `seq(...)` call |
| `when: first` | once-per-IOC commands (e.g. STREAM_PROTOCOL_PATH) |
