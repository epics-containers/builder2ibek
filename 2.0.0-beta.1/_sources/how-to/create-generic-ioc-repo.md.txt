# Create a Generic IOC repository

A Generic IOC is a container image (or RTEMS binary) that bundles one or more
support modules and can be configured at runtime by ibek from an `ioc.yaml` file.
This guide shows how to create the repository that produces the image.

## Prerequisites

- `copier` installed (`pip install copier` or `uvx copier`)
- Git and access to the `epics-containers` GitHub organisation
- The ibek support YAML for your module already exists in `ibek-support-dls`
  (see [](../tutorials/create-support-yaml.md))

---

## 1. Generate from ioc-template

[ioc-template](https://github.com/epics-containers/ioc-template) is a copier
template that scaffolds the Generic IOC repository.

```bash
uvx copier copy --trust gh:epics-containers/ioc-template ioc-<module>
```

Answer the prompts (IOC name, description, base image, etc.). This produces a
directory `ioc-<module>/` with:

```
ioc-<module>/
├── Dockerfile
├── ioc/                   # EPICS IOC application source
│   ├── iocApp/src/Makefile
│   └── configure/RELEASE
├── ibek-support/          # submodule: community support yaml
├── ibek-support-dls/      # submodule: DLS-specific support yaml
├── tests/
├── requirements.txt       # pinned ibek version
└── README.md
```

---

## 2. Add the ibek-support-dls submodule

If your module lives in `ibek-support-dls` rather than the community
`ibek-support`, add it as a submodule:

```bash
cd ioc-<module>
git submodule add https://gitlab.diamond.ac.uk/controls/containers/utils/ibek-support-dls
```

Or initialise the existing placeholder:

```bash
git submodule update --init ibek-support-dls
```

---

## 3. Edit the Dockerfile

The Dockerfile drives the container build.  Add `ansible.sh` invocations for
each support module you want to include.

Example — `ioc-hidenrga/Dockerfile`:

```dockerfile
ARG IMAGE_EXT

ARG REGISTRY=ghcr.io/epics-containers
ARG RUNTIME=${REGISTRY}/epics-base${IMAGE_EXT}-runtime:7.0.10ec1
ARG DEVELOPER=${REGISTRY}/ioc-asyn-developer:4.45ec3

##### build stage ##############################################################
FROM ${DEVELOPER} AS developer

ENV SOURCE_FOLDER=/epics/generic-source
RUN ln -s ${SOURCE_FOLDER}/ioc ${IOC}

# Get the current version of ibek
COPY requirements.txt requirements.txt
RUN uv pip install --upgrade -r requirements.txt

WORKDIR ${SOURCE_FOLDER}/ibek-support

COPY ibek-support/_ansible _ansible
ENV PATH=$PATH:${SOURCE_FOLDER}/ibek-support/_ansible

# Community support modules (iocStats provides devIocStats.iocAdminSoft)
COPY ibek-support/iocStats/ iocStats
RUN ansible.sh iocStats

COPY ibek-support/StreamDevice/ StreamDevice/
RUN ansible.sh StreamDevice

# DLS-specific support modules
WORKDIR ${SOURCE_FOLDER}/ibek-support-dls

COPY ibek-support-dls/hidenrga/ hidenrga/
RUN ansible.sh hidenrga

# Build the IOC
COPY ioc ${SOURCE_FOLDER}/ioc
RUN ansible.sh ioc

##### runtime preparation stage ################################################
FROM developer AS runtime_prep

RUN ibek ioc extract-runtime-assets /assets /python

##### runtime stage ############################################################
FROM ${RUNTIME} AS runtime

COPY --from=runtime_prep /assets /
RUN ibek support apt-install-runtime-packages

CMD ["bash", "-c", "${IOC}/start.sh"]
```

Key points:
- The `DEVELOPER` base image already provides asyn, StreamDevice, and other
  common support; build on top of it rather than starting from scratch.
- Each `ansible.sh <module>` call reads the module's `install.yml` and compiles
  the support.
- `ibek-support-dls` modules follow the same pattern as community modules.

---

## 4. Verify the ibek-support-dls module name

The folder name under `ibek-support-dls/` must be lowercase and match the name
used in `ansible.sh`:

```
ibek-support-dls/
└── hidenrga/              ← lowercase folder
    ├── hidenRGA.ibek.support.yaml
    └── hidenRGA.install.yml
```

The `module:` field inside `hidenRGA.ibek.support.yaml` must match the capitalised
module name as used in entity type prefixes (e.g. `hidenRGA.hidenRGA_qga`).

---

## 5. Build and test locally

With Docker (or Podman) available, test the build inside the devcontainer:

```bash
# Open in VSCode → "Reopen in Container"
# Or on the command line:
docker build -t ioc-hidenrga:dev .
```

Then run a test conversion to verify that ibek can resolve all entity types:

```bash
uv run builder2ibek xml2yaml tests/samples/MY-IOC.xml --yaml /tmp/my-ioc.yaml
ibek ioc generate --definitions /path/to/ibek-support-dls --ioc /tmp/my-ioc.yaml
```

---

## 6. Hybrid RTEMS variant

For RTEMS-beatnik (PowerPC) targets the approach differs slightly — a native
EPICS Makefile build is used instead of Docker:

- The repo structure is a standard EPICS application (see
  `/dls_sw/work/R7.0.7/ioc/BL/bl-va-ioc-01` as reference).
- `ibek-support/` and `ibek-support-dls/` are still present as submodules, but
  they are **not** used by `make` — they pin the ibek YAML versions that the
  `rtems-proxy` will use at runtime to generate `st.cmd`.
- The `src/Makefile` lists DBDs and libs explicitly; `ansible.sh` is not used.
- See the `AGENTS.md` in that repo for RTEMS-specific gotchas (e.g.
  `utilityRTEMS.dbd` vs `utility.dbd`).
