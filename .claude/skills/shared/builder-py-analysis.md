# Systematic builder.py analysis

A step-by-step procedure for reading a DLS EPICS support module's builder.py
and extracting its classes, parameters, databases, st.cmd commands, and
dependencies.

---

## Step 1: Locate source files

Find the module and its latest version:

```bash
ls /dls_sw/prod/R3.14.12.7/support/<module>/
```

Read all Python files in the `etc/` directory:

```bash
ls /dls_sw/prod/R3.14.12.7/support/<module>/<version>/etc/*.py
```

The primary file is `builder.py`, but some modules split logic across multiple
`.py` files (e.g. a `_classes.py` or `_templates.py`). Read all of them.

---

## Step 1b: Check for XML template files

Some modules define **XML template files** in `etc/makeIocs/` alongside the
IOC XMLs. These are XML files with `$(macro)` parameters that expand inline
into multiple child entities when included by an IOC XML.

```bash
# Look for XML files that use $(macro) syntax — these are templates
grep -l '$(.*)'  /dls_sw/prod/R3.14.12.7/support/<module>/<version>/etc/makeIocs/*.xml 2>/dev/null
```

The builder system auto-generates `auto_xml_<TEMPLATE_NAME>` classes from
these files. For example, `GIGE-FIT-TEMPLATE_G158B.xml` becomes the class
`auto_xml_GIGE_FIT_TEMPLATE_G158B`.

**How XML templates differ from db AutoSubstitution:**

| Feature | db AutoSubstitution (`auto_*`) | XML template (`auto_xml_*`) |
|---|---|---|
| Source | `.template` / `.db` file in `db/` | `.xml` file in `etc/makeIocs/` |
| What it produces | A single `dbLoadRecords` call | Multiple child entities (each with its own db, init commands, etc.) |
| Parameters | db macro declarations (`# % macro`) | `$(macro)` references in XML attributes |
| In ibek | One entity model with `databases` | Cannot be represented as a single entity — must expand to constituent entities |

**Reporting XML templates:**
- List the template parameters (extracted from `$(macro)` and `$(macro=default)` references)
- List what child entities it expands to (read the template XML)
- Note which support modules the child entities come from — these are the
  real dependencies

XML templates can appear in both BUILDER modules and support modules.

---

## Step 2: Identify classes and their base types

Each Python class in builder.py typically corresponds to one user-facing
component. Classify each class by its base type:

| Base type | Meaning |
|---|---|
| `AutoSubstitution` | Template-driven — macros auto-extracted from the db file |
| `AutoSubstitution` + `Device` | Template + custom init commands, dependencies, or libraries |
| `Device` only | Port creators, sequencers, pure init logic (no db template) |
| `ModuleBase` | Helper that conditionally instantiates other classes |

### Which classes need reporting?

**YES — report these:**
- Classes users instantiate in XML (they have `ArgInfo` and take parameters)
- Classes with `TemplateFile` (they load a database)
- Classes with `Initialise` / `PostIocInitialise` methods (they emit st.cmd commands)

**NO — skip these:**
- `AutoInstantiate = True` — singleton, created automatically, not user-facing
- `BaseClass = True` — abstract parent, never instantiated directly
- Simulation variants (e.g. `_Sim` suffix classes)
- Internal `_prefixed` template helper classes

---

## Step 3: Extract parameters from each class

### For `AutoSubstitution` classes

Parameters come from the template db file macros — see Step 4 below.

### For classes with explicit `ArgInfo`

Look for `makeArgInfo(__init__, ...)` declarations. These define the class's
parameter interface.

**Parameter type mapping:**

| builder.py declaration | Type | Notes |
|---|---|---|
| `Simple("desc", str)` | `str` | |
| `Simple("desc", int)` | `int` | |
| `Simple("desc", float)` | `float` | |
| `Choice("desc", ["A", "B"])` | enum | Allowed values listed |
| `Ident("desc", ClassName)` | object reference | Cross-reference to another class instance |

**Defaults:**
- Explicit defaults in `ArgInfo`: `makeArgInfo(__init__, PORT=Simple("...", str))`
  with default values in the `__init__` signature
- Class-level `Defaults = dict(PARAM=value, ...)` — these set defaults for
  inherited parameters

**Required vs optional:**
- Parameters in `required_names` (no default) — required
- Parameters in `default_names` (have a default) — optional

**Inheritance filtering:**
- `ArgInfo.filtered(without=["PARAM"])` removes inherited params from child
  classes — these params are handled by the parent and should not be reported
  on the child

---

## Step 4: Analyze database files

Find compiled db files:

```bash
ls /dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/
```

Match `TemplateFile = 'foo.db'` in the Python class to the actual db file.

Read macro declarations:

```bash
grep "^# % macro" /dls_sw/prod/R3.14.12.7/support/<module>/<version>/db/<file>.db
```

Format: `# % macro, NAME, Description`

**Required vs optional macros:**
- Macros that appear in record fields without a default (e.g. `$(NAME)`) are
  required
- Macros with a default (e.g. `$(NAME=default_value)`) are optional — the
  default value is what the db file uses if the macro is not supplied

For `AutoSubstitution` classes, ALL macros become parameters automatically.

For wrapper classes (non-AutoSubstitution), only macros explicitly passed in
the `__init__` method are relevant.

**Inherited templates:**
- `@includesTemplates(OtherClass)` — this class's db includes another class's
  template. The included template's macros are also required.
- `.subst` file includes — check if the db file is actually a `.subst` that
  includes other db files.

---

## Step 5: Extract st.cmd commands

Read the class methods that emit startup script commands:

| Method | When it runs | Notes |
|---|---|---|
| `Initialise()` | Before `iocInit` | Pre-init commands |
| `InitialiseOnce()` | Before `iocInit`, first instance only | Singleton init |
| `PostIocInitialise()` | After `iocInit` | Post-init commands |
| `Initialise_FIRST()`, `Initialise_1()` etc. | Ordering variants | Same as `Initialise` but with phase control |

**Reading method bodies:**
- Methods use `print` statements with `%` string formatting
- `print("drvFooConfig(%(PORT)s, %(ADDR)d)" % self.__dict__)` emits a
  `drvFooConfig` call with the entity's PORT and ADDR values
- Map `%(name)s` / `%(name)d` format strings to entity parameters

**Dependency-contributed commands:**
These do NOT appear in the class methods. Check the `Dependencies = (...)`
tuple — dependencies like `Asyn` contribute their own init commands (e.g.
`drvAsynIPPortConfigure`). These are handled by the dependency's own class,
not by this one. Report them as dependencies, not as this class's commands.

**Finding real boot scripts for comparison:**
To see what a fully expanded VxWorks boot script looks like for this module:

```bash
# Find IOCs that use this module
grep -i <module> $(find /dls_sw/work/R3.14.12.7/support/*BUILDER/etc/makeIocs -maxdepth 5 -name "*.xml") | head -5
```

Then find the corresponding `.boot` file to see the actual startup commands in
context.

---

## Step 6: Extract install information

These class-level attributes declare what the module needs compiled/installed:

| Attribute | Purpose |
|---|---|
| `DbdFileList = [...]` | DBD files to include |
| `LibFileList = [...]` | Libraries to link |
| `ProtocolFiles = [...]` | StreamDevice protocol files to copy |

These are typically on the main `Device`-derived class. Some modules set them
on a base class; check parent classes too.

---

## Step 7: Identify dependencies and cross-references

**Dependencies tuple:**
- `Dependencies = (ModuleA, ModuleB)` lists modules that must be loaded before
  this one
- These determine build order and what support modules must be present

**Cross-references between classes:**
- `Ident("desc", OtherClass)` parameters reference instances of `OtherClass`
- Port-creating classes (inherit from `AsynPort` or similar) — their `name`
  parameter is the identifier other classes use to reference them
- The referencing class uses `Ident("desc", PortClass)` to accept a port name

**Common port pattern:**
- Port creator: has a `name` / `port` parameter that identifies it
- Port consumer: has a `PORT` parameter of type `Ident` pointing to the creator
- In XML, both share a matching string value
