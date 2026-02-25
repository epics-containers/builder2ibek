# Verify a converted IOC using db-compare

After converting a builder XML IOC to `ioc.yaml`, the most rigorous way to
verify correctness is to run the Generic IOC inside the devcontainer, generate
the EPICS database, and compare it record-by-record against the original
builder-compiled `_expanded.db`.

`builder2ibek db-compare` performs this comparison, normalising floating-point
values and ignoring order, so it catches genuine record and field differences
rather than cosmetic ones.

## Prerequisites

- A Generic IOC repo (e.g. `ioc-hidenrga`) cloned locally with the devcontainer
  configured
- The converted `ioc.yaml` (see [](convert-ioc-instance.md))
- The original `_expanded.db` from the builder IOC build, accessible on the host
  (typically under `/dls_sw/.../<IOC>/db/<IOC>_expanded.db`)
- Docker or Podman, and VSCode with the Dev Containers extension

---

## 1. Prepare the IOC instance config

The devcontainer expects the instance configuration in a folder containing
`ioc.yaml`. Make sure your services repository is cloned next to your
generic IOC folder e.g.

For example, to test `BL11I-CS-IOC-09` which is a ioc-hidenrga based IOC we
would need:

```
my-work-folder/
├── ioc-hidenrga
└── i11-services
    └── services
        └── bl11i-cs-ioc-09
            ├── config/
            │   └── ioc.yaml        ← your converted ioc.yaml goes here
            ├── values.yaml
            └── templates
```



---

## 2. Open the Generic IOC in the devcontainer

First make sure the `ibek-support*` submodules are present
  - `git submodule update --init`

Open the Generic IOC repository in VSCode and choose
**"Reopen in Container"**. This builds the developer image, compiles all
support modules, and drops you into a shell with:

- `/epics/ioc/` — the compiled IOC binary
- `/epics/support/` — all support libraries, DBs, and protocol files
- `/epics/ibek-defs/` — combined ibek schema for the container

The `ibek-support` and `ibek-support-dls` submodules from the repo are mounted
at `/epics/generic-source/ibek-support*`, so edits to support YAML are
immediately visible inside the container.

---

## 3. Point the devcontainer at your instance

Inside the devcontainer terminal, use `ibek dev instance` to symlink your
instance config folder to `/epics/ioc/config`:

```bash
ibek dev instance /workspaces/i11-services/services/bl11i-cs-ioc-09
```

This creates:
```
/epics/ioc/config -> /workspaces/i11-services/services/bl11i-cs-ioc-09/config
```

Because it is a symlink any edits to `ioc.yaml` on the host are immediately
reflected inside the container without restarting.

---

## 4. Generate the EPICS runtime files

Generate `st.cmd` and the compiled database without actually launching the IOC:

```bash
ibek runtime generate /epics/ioc/config/ioc.yaml \
    /epics/generic-source/ibek-support-dls/hidenRGA/hidenRGA.ibek.support.yaml \
    /epics/generic-source/ibek-support/iocStats/iocStats.ibek.support.yaml \
    ... (all relevant support yaml files)
```

Or, more conveniently, let `start.sh` do it (it calls `ibek runtime generate2`
which discovers YAML files automatically from `/epics/generic-source`):

```bash
/epics/ioc/start.sh
```

After generation, the runtime assets are in `/epics/runtime/`:
```
/epics/runtime/
├── st.cmd      ← generated startup script
├── ioc.db      ← fully expanded EPICS database
└── protocol/   ← StreamDevice protocol files
```

To generate without starting the IOC (useful for DB comparison only), stop
after ibek's generation step:

```bash
ibek runtime generate2 /epics/ioc/config
```

---

## 5. Compare with the original DB

The original builder IOC's expanded database lives in the builder tree at:

```
/dls_sw/work/R3.14.12.7/support/BL11I-BUILDER/iocs/BL11I-CS-IOC-09/db/BL11I-CS-IOC-09_expanded.db
```

(Host path — mounted at the same location in the devcontainer since `dls_sw`
is typically bind-mounted.)

Run `builder2ibek db-compare`:

```bash
uv run builder2ibek db-compare \
    /dls_sw/work/R3.14.12.7/support/BL11I-BUILDER/iocs/BL11I-CS-IOC-09/db/BL11I-CS-IOC-09_expanded.db \
    /epics/runtime/ioc.db
```

Example output when the databases match:

```
*******************************************************************
Records in original but not in new:


*******************************************************************
Records in new but not in original:


*******************************************************************
records in original:    37755
  records in new:         37755
  records missing in new: 0
  records extra in new:   0
*******************************************************************
```

Save the output to a file for review:

```bash
uv run builder2ibek db-compare \
    /dls_sw/.../BL11I-CS-IOC-09_expanded.db \
    /epics/runtime/ioc.db \
    --output compare.diff
```

---

## 6. Interpret the output

**Records in original but not in new** — records present in the builder IOC but
missing from the ibek-generated DB.  These represent features not yet covered
by the support YAML.  Investigate whether they come from a support module that
needs an entity model, or from a `dbLoadRecords` call that needs adding to
`pre_init` or `databases`.

**Records in new but not in original** — extra records added by ibek.  Often
benign additions from `devIocStats` or `autosave`, but worth checking.

**Fields … are different** — a record exists in both but has field-value
differences.  Usually caused by a macro not being passed correctly, a default
value differing between builder and ibek, or a template version mismatch.

---

## 7. Iterating on discrepancies

When you find differences:

1. **Missing module records**: add the module to `ibek-support-dls` following
   the [](../tutorials/create-support-yaml.md) and
   rebuild the devcontainer (or run `ibek dev support <module-path>` to
   hot-load the module without a full rebuild).

2. **Wrong macro values**: check `databases.args` in the support YAML and
   compare with the original substitution file.

3. **Wrong record type** (e.g. `genSub` vs `aSub`): this typically means the
   generic IOC is using a different version of the support module than the
   original builder IOC. Check the module version in `install.yml`.

4. **Expected differences**: use `--ignore` to suppress known-good differences,
   e.g. IOC statistics records that always have different names:

```bash
uv run builder2ibek db-compare \
    original.db new.db \
    --ignore "BL11I-CS-IOC-09:VERSION" \
    --ignore ":HEARTBEAT"
```

---

## Quick reference

| Step | Command |
|---|---|
| Point devcontainer at instance | `ibek dev instance /workspaces/my-project/iocs/my-ioc` |
| Generate runtime files only | `ibek runtime generate2 /epics/ioc/config` |
| Compare databases | `uv run builder2ibek db-compare original.db /epics/runtime/ioc.db` |
| Save comparison to file | `... --output compare.diff` |
| Ignore specific records | `... --ignore "PATTERN"` |
| Remove duplicates in original | `... --remove-duplicates` |
| Hot-load a support module | `ibek dev support /epics/generic-source/ibek-support-dls/mymodule` |
