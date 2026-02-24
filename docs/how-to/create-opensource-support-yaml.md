# Create ibek-support YAML for a builder.py module

This guide covers the same conversion task as the
[DLS-internal tutorial](../tutorials/create-support-yaml.md) but targets the
public [epics-containers/ibek-support](https://github.com/epics-containers/ibek-support)
repository on GitHub, making the support available to the whole EPICS community.

The full upstream walkthrough (including how to set up a Generic IOC from
scratch) is the epics-containers tutorial:

> [Creating a Generic IOC — Lakeshore 340](https://epics-containers.github.io/main/tutorials/generic_ioc.html#lakeshore-340-temperature-controller)

This page focuses on the differences from the internal DLS workflow and gives
concise steps for the common case of migrating a DLS module to the open-source
ecosystem.

## When to use ibek-support vs ibek-support-dls

Use **ibek-support** (open-source, GitHub) when:
- The EPICS support module itself is already open-source or could be published
- Other facilities are likely to use the same hardware
- The module has no site-specific hard-coded paths or licenced code

Use **ibek-support-dls** (internal, DLS GitLab) when:
- The module is proprietary or DLS-specific
- The module source lives on DLS GitLab and cannot be published
- The hardware is unique to Diamond

---

## Prerequisites

- A GitHub account and access to fork
  [epics-containers/ibek-support](https://github.com/epics-containers/ibek-support)
- The module source published (or publishable) to a public GitHub organisation
- A Generic IOC repo (e.g. from
  [ioc-template](https://github.com/epics-containers/ioc-template)) in which to
  test

---

## 1. Publish the support module source

Before contributing ibek support YAML, the module source itself must be
publicly accessible.  For a DLS module on GitLab, the typical steps are:

1. Mirror or push the module to a GitHub organisation
   (e.g. `https://github.com/DiamondLightSource/<module>`)
2. Add an `Apache-2.0` or equivalent open-source licence
3. Ensure `configure/RELEASE` includes `RELEASE.local` so the module builds
   outside DLS without modification
4. Tag a release (e.g. `2-6-4`) — the tag becomes the `version:` field

---

## 2. Fork ibek-support

Create a personal or organisation fork of
[epics-containers/ibek-support](https://github.com/epics-containers/ibek-support).

In your Generic IOC repo, update the `ibek-support` submodule to point to
your fork using an **HTTPS URL** (required for CI to clone without SSH keys):

```bash
git submodule set-url ibek-support https://github.com/<your-fork>/ibek-support
git submodule update --remote ibek-support
cd ibek-support
git checkout -b add-<module>
```

Configure your local git to transparently use SSH for pushes while keeping
the submodule URL as HTTPS:

```ini
# ~/.gitconfig
[url "ssh://git@github.com/"]
    insteadOf = https://github.com/
```

---

## 3. Write the install.yml

Create `ibek-support/<module>/<module>.install.yml`.

The format is the same as for `ibek-support-dls` but the `organization` field
points to the public GitHub URL, and `ansible.sh` will clone the module fresh
from GitHub during the Docker build:

```yaml
# yaml-language-server: $schema=../../ibek-support/_scripts/support_install_variables.json

module: hidenRGA
version: 1-12
organization: https://github.com/DiamondLightSource

dbds:
  - hidenRGASupport.dbd
  - sncHidenRGA.dbd

libs:
  - hidenRGA

protocol_files:
  - hidenRGAApp/protocol/hiden_rga.proto
```

If the upstream Makefile builds documentation or other artefacts that fail
outside DLS, add `comment_out` rules:

```yaml
comment_out:
  - path: Makefile
    regexp: documentation
```

**Difference from ibek-support-dls**: `organization` is a public GitHub URL
rather than `https://gitlab.diamond.ac.uk/controls/support`.  There are no
other structural differences.

---

## 4. Write the ibek.support.yaml

Create `ibek-support/<module>/<module>.ibek.support.yaml`.

The content is identical to the DLS-internal version.  Follow the same steps
as in the [DLS-internal tutorial](../tutorials/create-support-yaml.md):

1. Read `builder.py` — each class → one `entity_model`
2. Identify runtime vs baked-in macros from the substitution files
3. Map XML attribute names to ibek parameter names exactly
4. Write `pre_init`, `databases`, `post_init` from the example boot script

The `hidenRGA` YAML from the tutorial applies here without change — the
entity model format is the same regardless of which repository hosts it.

---

## 5. Test in the devcontainer

Point your Generic IOC at the fork branch:

```bash
cd ibek-support
git add .
git commit -m "add hidenRGA support module"
```

In the devcontainer, install the new module:

```bash
ansible.sh hidenRGA
```

Then rebuild the IOC and verify the schema:

```bash
cd /epics/ioc && make
ibek ioc generate-schema > /tmp/ibek.ioc.schema.json
```

Run `builder2ibek db-compare` to verify the generated database matches the
original builder IOC — see
[Verify with devcontainer and db-compare](verify-with-devcontainer.md).

---

## 6. Update the Generic IOC Dockerfile

Add the new support module to the Dockerfile build sequence, after any
dependencies it needs:

```dockerfile
# dependencies (if not already present)
COPY ibek-support/asyn/ asyn/
RUN ansible.sh asyn

COPY ibek-support/StreamDevice/ StreamDevice/
RUN ansible.sh StreamDevice

# new module
COPY ibek-support/hidenRGA/ hidenRGA/
RUN ansible.sh hidenRGA
```

---

## 7. Push and open a pull request to ibek-support

Once tested, push the feature branch and open a pull request against
`epics-containers/ibek-support`:

```bash
cd ibek-support
git push -u origin add-hidenRGA
```

Then open a PR on GitHub.  The maintainers will review for:
- General utility to other facilities
- Security (no DLS-specific hard-coded paths, no private credentials)
- Schema validity

While the PR is in review, you can keep your Generic IOC submodule pointed at
your fork branch.  Once merged, update to `origin/main`:

```bash
git submodule set-url ibek-support https://github.com/epics-containers/ibek-support
git submodule update --remote ibek-support
```

---

## Key differences from the DLS-internal workflow

| Aspect | ibek-support (open-source) | ibek-support-dls (internal) |
|---|---|---|
| Repository | `epics-containers/ibek-support` on GitHub | DLS GitLab |
| `organization` in install.yml | `https://github.com/<org>` | `https://gitlab.diamond.ac.uk/controls/support` |
| Module source | Must be public on GitHub | Can be private on DLS GitLab |
| Contribution | PR to GitHub | Commit / MR to DLS GitLab |
| Submodule URL | HTTPS GitHub URL | DLS GitLab URL |
| ibek.support.yaml format | Identical | Identical |
| Dockerfile `ansible.sh` call | Identical | Identical |
