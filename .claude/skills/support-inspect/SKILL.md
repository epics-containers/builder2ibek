---
name: support-inspect
description: Analyze a support module's builder.py and report its classes, parameters, databases, st.cmd commands, and dependencies.
argument-hint: <module-name>
---

# Support Module Inspector

Analyze the DLS EPICS support module `$0` by reading its builder.py and related
source files, then produce a structured report.

This skill has **no knowledge of ibek** — it reports what builder.py defines,
not how to translate it. Use `/ioc-convert` for the ibek translation workflow.

---

## Workflow

### 1. Locate the module

Find the latest version:

```bash
ls /dls_sw/prod/R3.14.12.7/support/$0/
```

Pick the latest version directory. If not found in `prod`, try:

```bash
ls /dls_sw/work/R3.14.12.7/support/$0/
```

If the module is not found at all, report this and stop.

### 2. Read all source files

```bash
ls /dls_sw/prod/R3.14.12.7/support/$0/<version>/etc/*.py
```

Read every `.py` file found. The primary file is `builder.py` but some modules
split across multiple files.

### 3. Analyze using the shared methodology

Follow the step-by-step procedure in
[builder-py-analysis.md](../shared/builder-py-analysis.md) to extract:

- Classes and their base types (Step 2)
- Parameters with types, defaults, and required/optional status (Step 3)
- Database files and their macros (Step 4)
- st.cmd commands — pre_init, post_init, once-only (Step 5)
- Install information — DBDs, libraries, protocol files (Step 6)
- Dependencies and cross-references (Step 7)

### 4. Find a real IOC example

Search for IOC XMLs that use this module.

First, discover which EPICS versions exist:
```bash
ls -d /dls_sw/prod/R*
```

Then search each version, starting with R3.14.12.7 (the most common), looping
through all others in a single command. Stop as soon as a match is found.

```bash
# Search work and prod for all known EPICS versions in one go
for v in $(ls -d /dls_sw/prod/R* | sort -rV | xargs -n1 basename); do
  result=$(grep -rl "$0" $(find /dls_sw/work/$v/support/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml" 2>/dev/null) 2>/dev/null | head -3)
  if [ -n "$result" ]; then echo "=== work/$v ==="; echo "$result"; break; fi
  result=$(grep -rl "$0" $(find /dls_sw/prod/$v/support/*/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml" 2>/dev/null) 2>/dev/null | head -3)
  if [ -n "$result" ]; then echo "=== prod/$v ==="; echo "$result"; break; fi
done
```

Note: `work` has no version subdirs under support modules; `prod` has an extra
`*/` level (e.g. `.../support/FOO-BUILDER/1-5/etc/makeIocs/`).

If found, note the XML path and look for the corresponding boot script for
context on how the module's st.cmd commands appear in practice.

### 5. Produce the report

Format the output as a structured report:

```
## Module: <module> (<version>)

Source: /dls_sw/prod/R3.14.12.7/support/<module>/<version>/etc/builder.py

### Classes

#### <ClassName>
- **Base type**: AutoSubstitution + Device
- **Database**: `<file>.db`
- **Parameters**:
  | Name | Type | Required | Default | Description |
  |------|------|----------|---------|-------------|
  | P    | str  | yes      | —       | Device prefix |
  | PORT | object (AsynPort) | yes | — | Asyn port reference |
  | ...  | ...  | ...      | ...     | ...         |
- **pre_init**:
  - `drvFooConfig("%(PORT)s", %(ADDR)d)` (from Initialise)
- **post_init**:
  - `seq(sncFoo, "P=%(P)s")` (from PostIocInitialise)
- **Dependencies**: Asyn, Calc

#### <ClassName2>
...

### Install information
- **DBDs**: foo, fooSupport
- **Libraries**: foo
- **Protocol files**: foo.proto

### Example IOC
- **XML**: /dls_sw/work/.../BL21I-FOO-IOC-01.xml
- **Boot script**: /dls_sw/prod/.../BL21I-FOO-IOC-01.boot
```

**Notes on the report:**
- List ALL user-facing classes (skip AutoInstantiate, BaseClass, simulation variants)
- For each parameter, show the raw builder.py type (str, int, float, enum, Ident)
- Show st.cmd commands with their original `%` format strings — do not convert
  to Jinja2 or any other format
- If a class has no init commands, say "(none)" rather than omitting the section
- List dependencies from both the `Dependencies` tuple and any `Ident` parameters
