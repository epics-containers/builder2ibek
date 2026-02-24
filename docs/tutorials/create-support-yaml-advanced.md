# Advanced: ibek support YAML for a complex builder.py

This tutorial extends the
[basic tutorial](create-support-yaml.md) to cover patterns that arise in
more complex modules: `InitialiseOnce`, cross-referencing other entities as
`type: object`, templates that include shared base templates, and `install.yml`
fields for system package dependencies and Makefile patching.

We use the **`ffmpegServer`** support module as the concrete example.  It is
open-source at
[DiamondLightSource/ffmpegServer](https://github.com/DiamondLightSource/ffmpegServer)
and its ibek support YAML lives in
[epics-containers/ibek-support](https://github.com/epics-containers/ibek-support).

By the end of this tutorial you will understand how:
- `ibek-support/ffmpegServer/ffmpegServer.ibek.support.yaml` was written
- `ibek-support/ffmpegServer/ffmpegServer.install.yml` was written

---

## Prerequisites

- Completed (or familiar with) the
  [basic tutorial](create-support-yaml.md)
- A GitHub account and fork of
  [epics-containers/ibek-support](https://github.com/epics-containers/ibek-support)
- Access to the [ffmpegServer module source](https://github.com/DiamondLightSource/ffmpegServer) published on GitHub

---

## 1. Read builder.py

`/dls_sw/prod/R3.14.12.7/support/ffmpegServer/3-1dls17/etc/builder.py`:

```python
class FFmpegServer(Device):
    '''Library dependencies for ffmpeg'''
    Dependencies = (ADCore,)
    LibFileList = ['swresample', 'swscale', 'avutil', 'avcodec', 'avformat', 'avdevice', 'ffmpegServer']
    DbdFileList = ['ffmpegServer']
    AutoInstantiate = True

@includesTemplates(NDPluginBaseTemplate)
class _ffmpegStream(AutoSubstitution):
    TemplateFile = 'ffmpegStream.template'

class ffmpegStream(AsynPort):
    '''This plugin provides an http server that produces an mjpeg stream'''
    Dependencies = (FFmpegServer,)
    UniqueName = "PORT"
    _SpecificTemplate = _ffmpegStream

    def __init__(self, PORT, NDARRAY_PORT, QUEUE=2, HTTP_PORT=8080,
                 BLOCK=0, NDARRAY_ADDR=0, MEMORY=0, ENABLED=1, **args):
        ...

    def InitialiseOnce(self):
        print("ffmpegServerConfigure(%(HTTP_PORT)d)" % self.__dict__)

    def Initialise(self):
        print('ffmpegStreamConfigure('
              '"%(PORT)s", %(QUEUE)d, %(BLOCK)d, "%(NDARRAY_PORT)s", '
              '"%(NDARRAY_ADDR)s", %(MEMORY)d)' % self.__dict__)

class ffmpegFile(AsynPort):
    ...
    def Initialise(self):
        print('ffmpegFileConfigure('
              '"%(PORT)s", %(QUEUE)d, %(BLOCK)d, "%(NDARRAY_PORT)s", '
              '%(NDARRAY_ADDR)s, %(BUFFERS)d, %(MEMORY)d)' % self.__dict__)
```

### Key observations

| Observation | Implication |
|---|---|
| `FFmpegServer` has `AutoInstantiate = True` | It is loaded automatically by xmlbuilder; it does **not** become a user-facing entity model |
| `ffmpegStream` and `ffmpegFile` are `AsynPort` subclasses | Each becomes one `entity_model` |
| `UniqueName = "PORT"` | `PORT` is the unique identifier per instance, maps to `type: id` in ibek |
| `_ffmpegStream` uses `@includesTemplates(NDPluginBaseTemplate)` | Macros from the base template (`SCANRATE`, `PRIORITY`, `STACKSIZE`) are also runtime parameters |
| `InitialiseOnce` on `ffmpegStream` | `ffmpegServerConfigure()` runs **once per IOC** regardless of how many streams are configured — maps to `when: first` |
| `NDARRAY_PORT` is declared `Ident('...', AsynPort)` | It is a reference to another entity's port — maps to `type: object` |

---

## 2. `AutoInstantiate` classes — no entity model needed

`FFmpegServer` only carries library/dbd dependencies.  In ibek these are
expressed in `install.yml` (`libs`, `dbds`), not in `ibek.support.yaml`.
**Do not create an entity model for it.**

---

## 3. `InitialiseOnce` → `when: first`

The `ffmpegServerConfigure()` call must appear exactly once in `st.cmd` even
when multiple `ffmpegStream` instances are created.  In ibek this is expressed
with `when: first` on the `pre_init` entry:

```yaml
pre_init:
  - when: first
    value: |
      ffmpegServerConfigure({{HTTP_PORT}})
  - value: |
      # ffmpegStreamConfigure(portName, queueSize, blockingCallbacks,
      #                        NDArrayPort, NDArrayAddr, maxBuffers, maxMemory,
      #                        priority, stackSize)
      ffmpegStreamConfigure("{{PORT}}", {{QUEUE}}, {{BLOCK}},
          "{{NDARRAY_PORT}}", {{NDARRAY_ADDR}}, {{BUFFERS}}, {{MEMORY}},
          {{PRIORITY}}, {{STACKSIZE}})
```

ibek emits the `when: first` block only for the first entity of this type
that it encounters in `ioc.yaml`.

---

## 4. `NDARRAY_PORT` — cross-referencing another entity

In builder XML, `NDARRAY_PORT` is an `Ident` argument that references another
`AsynPort` instance by its `PORT` name:

```xml
<ffmpegServer.ffmpegStream PORT="C1.MJPG" NDARRAY_PORT="C1.CAM"
    P="BLxxI-DI-PHDGN-01" R=":MJPG:" HTTP_PORT="8081" ADDR="0"/>
```

In ibek `type: object` expresses a reference to another entity's `id`:

```yaml
NDARRAY_PORT:
  type: object
  description: Input array port
```

At runtime ibek renders `{{NDARRAY_PORT}}` to the string value of the
referenced entity's `id` field (i.e. its PORT name), so the
`ffmpegStreamConfigure` call gets the correct port name.

In `databases.args`, `NDARRAY_PORT` is passed directly to `dbLoadRecords`
so the template receives the right `$(NDARRAY_PORT)` macro:

```yaml
databases:
  - file: $(FFMPEGSERVER)/db/ffmpegStream.template
    args:
      PORT:
      P:
      R:
      NDARRAY_PORT:
      MAXW:
      MAXH:
      QUALITY:
      SETW:
      SETH:
```

---

## 5. Macros from included base templates

`_ffmpegStream` is decorated with `@includesTemplates(NDPluginBaseTemplate)`.
This merges the base template's macro set into `_ffmpegStream.ArgInfo`.
Macros defined in `NDPluginBaseTemplate` that are **not** baked in by
substitution patterns survive as runtime macros and must also appear in the
ibek entity parameters.

For `ffmpegStream` the relevant inherited macros are `SCANRATE`, `PRIORITY`,
and `STACKSIZE`, which appear in `NDPluginBase.template` records.  Add them
to the entity model with their builder defaults:

```yaml
PRIORITY:
  type: int
  description: Thread priority if ASYN_CANBLOCK is set
  default: 0
SCANRATE:
  type: enum
  description: Scan rate for cpu-intensive PVs
  values:
    Passive:
    I/O Intr:
    .1 second:
    .2 second:
    .5 second:
    1 second:
    2 second:
    5 second:
    10 second:
    Event:
  default: I/O Intr
STACKSIZE:
  type: int
  description: Stack size if ASYN_CANBLOCK is set
  default: 0
```

---

## 6. Write the ibek.support.yaml

`ibek-support/ffmpegServer/ffmpegServer.ibek.support.yaml`:

```yaml
# yaml-language-server: $schema=https://github.com/epics-containers/ibek/releases/download/3.1.2/ibek.support.schema.json

module: ffmpegServer

entity_models:

  - name: ffmpegStream
    description: |-
      Provides an http server that returns an mjpeg stream of NDArrays over http.
    parameters:
      PORT:
        type: id
        description: Port name for the ffmpegStream areaDetector plugin
      P:
        type: str
        description: Device Prefix
      R:
        type: str
        description: Device Suffix
      NDARRAY_PORT:
        type: object
        description: Input array port
      HTTP_PORT:
        type: int
        description: HTTP port for the mjpeg server
        default: 8080
      QUEUE:
        type: int
        description: Input array queue size
        default: 2
      BLOCK:
        type: int
        description: Blocking callbacks?
        default: 0
      NDARRAY_ADDR:
        type: int
        description: Input array port address
        default: 0
      BUFFERS:
        type: int
        description: Max buffers to allocate
        default: 50
      MEMORY:
        type: int
        description: Max memory to allocate
        default: 0
      MAXW:
        type: int
        description: Maximum Jpeg Width
        default: 1600
      MAXH:
        type: int
        description: Maximum Jpeg Height
        default: 1200
      SETW:
        type: int
        description: Set initial Jpeg Width
        default: 0
      SETH:
        type: int
        description: Set initial Jpeg Height
        default: 0
      QUALITY:
        type: int
        description: Quality of the JPEG compression in percent
        default: 100
      PRIORITY:
        type: int
        description: Thread priority if ASYN_CANBLOCK is set
        default: 0
      SCANRATE:
        type: enum
        description: Scan rate for cpu-intensive PVs
        values:
          Passive:
          I/O Intr:
          .1 second:
          .2 second:
          .5 second:
          1 second:
          2 second:
          5 second:
          10 second:
          Event:
        default: I/O Intr
      STACKSIZE:
        type: int
        description: Stack size if ASYN_CANBLOCK is set
        default: 0

    pre_init:
      - when: first
        value: |
          ffmpegServerConfigure({{HTTP_PORT}})
      - value: |
          # ffmpegStreamConfigure(portName, queueSize, blockingCallbacks,
          #                        NDArrayPort, NDArrayAddr, maxBuffers, maxMemory,
          #                        priority, stackSize)
          ffmpegStreamConfigure("{{PORT}}", {{QUEUE}}, {{BLOCK}}, "{{NDARRAY_PORT}}", {{NDARRAY_ADDR}}, {{BUFFERS}}, {{MEMORY}}, {{PRIORITY}}, {{STACKSIZE}})

    databases:
      - file: $(FFMPEGSERVER)/db/ffmpegStream.template
        args:
          PORT:
          P:
          R:
          NDARRAY_PORT:
          MAXW:
          MAXH:
          QUALITY:
          SETW:
          SETH:

  - name: ffmpegFile
    description: |-
      Compresses a stream of NDArrays to video format and writes them to file.
    parameters:
      PORT:
        type: id
        description: Port name for the ffmpegFile areaDetector plugin
      P:
        type: str
        description: Device Prefix
      R:
        type: str
        description: Device Suffix
      NDARRAY_PORT:
        type: object
        description: Input array port
      QUEUE:
        type: int
        description: Input array queue size
        default: 2
      BLOCK:
        type: int
        description: Blocking callbacks?
        default: 0
      NDARRAY_ADDR:
        type: int
        description: Input array port address
        default: 0
      BUFFERS:
        type: int
        description: Max buffers to allocate
        default: 50
      MEMORY:
        type: int
        description: Max memory to allocate
        default: 0
      PRIORITY:
        type: int
        description: Thread priority if ASYN_CANBLOCK is set
        default: 0
      STACKSIZE:
        type: int
        description: Stack size if ASYN_CANBLOCK is set
        default: 0

    pre_init:
      - value: |
          # ffmpegFileConfigure(portName, queueSize, blockingCallbacks,
          #                      NDArrayPort, NDArrayAddr, maxBuffers, maxMemory,
          #                      priority, stackSize)
          ffmpegFileConfigure("{{PORT}}", {{QUEUE}}, {{BLOCK}}, "{{NDARRAY_PORT}}", {{NDARRAY_ADDR}}, {{BUFFERS}}, {{MEMORY}}, {{PRIORITY}}, {{STACKSIZE}})

    databases:
      - file: $(FFMPEGSERVER)/db/ffmpegFile.template
        args:
          PORT:
          P:
          R:
          NDARRAY_PORT:
```

---

## 7. Write the install.yml

`ffmpegServer` links against system ffmpeg libraries rather than building them
from source.  The `install.yml` uses `apt_developer` and `apt_runtime` to
declare the required system packages, and `comment_out` / `patch_lines` to
adapt the upstream Makefile.

`ibek-support/ffmpegServer/ffmpegServer.install.yml`:

```yaml
# yaml-language-server: $schema=../../ibek-support/_scripts/support_install_variables.json

module: ffmpegServer
version: 3d192ed
organization: https://github.com/DiamondLightSource

dbds:
  - ffmpegServer.dbd

libs:
  - ffmpegServer

apt_developer:
  - libavcodec-dev
  - libswscale-dev
  - libavformat-dev

apt_runtime:
  - libavcodec60
  - libswscale7
  - libavformat60

comment_out:
  # skip building vendored ffmpeg libraries
  - path: Makefile
    regexp: vendor
  - path: ffmpegServerApp/src/Makefile
    regexp: vendor\/ffmpeg

patch_lines:
  # link against system ffmpeg instead of vendored build
  - path: ffmpegServerApp/src/Makefile
    regexp: LIB_LIBS \+= avdevice
    line: ffmpegServer_SYS_LIBS += avformat avcodec swresample swscale avutil
```

### `install.yml` advanced fields explained

| Field | Purpose |
|---|---|
| `apt_developer` | Packages installed into the **builder** Docker image layer (headers, `-dev` packages needed to compile) |
| `apt_runtime` | Packages installed into the **runtime** Docker image layer (shared libraries needed to run the IOC) |
| `comment_out` | Lines matching `regexp` in the specified file are commented out during the Docker build |
| `patch_lines` | Lines matching `regexp` are replaced by `line` during the Docker build; here it switches from vendored to system ffmpeg |

---

## 8. Test in the devcontainer

With the files written into `ibek-support/ffmpegServer/`, install and verify
inside the Generic IOC devcontainer:

```bash
ansible.sh ffmpegServer
cd /epics/ioc && make
ibek ioc generate-schema > /tmp/ibek.ioc.schema.json
```

Convert a real IOC XML that uses ffmpegServer and verify with db-compare:

```bash
uvx builder2ibek xml2yaml example.xml --yaml /tmp/test.yaml
# then verify with ibek dev instance + db-compare
# see verify-with-devcontainer.md
```

---

## Summary of advanced patterns

| builder.py pattern | ibek mapping |
|---|---|
| `AutoInstantiate = True` | No entity model; handled by `libs`/`dbds` in `install.yml` |
| `InitialiseOnce` | `pre_init` entry with `when: first` |
| `Ident(...)` argument | `type: object` parameter |
| `UniqueName = "PORT"` | `PORT` parameter has `type: id` |
| `@includesTemplates(Base)` | Add the base template's runtime macros to the entity parameters |
| System package dependencies | `apt_developer` / `apt_runtime` in `install.yml` |
| Upstream Makefile incompatibilities | `comment_out` / `patch_lines` in `install.yml` |
