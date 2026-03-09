---
name: ioc-inspect
description: Inspect an IOC's XML definition, support modules, and component arguments
argument-hint: <ioc-name>
---

# IOC Inspector

Inspect the DLS EPICS IOC `$0` by locating its builder XML definition,
resolving support module paths, and reporting what components it uses with
their arguments.

This skill is **read-only** — it makes no changes to any files.

---

## Step 1 — Locate the IOC XML

Extract the beamline prefix from the IOC name:
- Input: `$0`
- Uppercase the name: e.g. `bl21i-va-ioc-01` → `BL21I-VA-IOC-01`
- Prefix = segment before the first `-`: `BL21I`
- BUILDER dir = `<PREFIX>-BUILDER`: `BL21I-BUILDER`

Search for the XML in this order (stop at first found):

1. `/dls_sw/work/R3.14.12.7/support/<BUILDER>/etc/makeIocs/<IOC-NAME>.xml`
2. `/dls_sw/prod/R3.14.12.7/support/<BUILDER>/*/etc/makeIocs/<IOC-NAME>.xml`
   (pick the highest version)
3. Other EPICS versions in prod:
   ```bash
   for v in $(ls -d /dls_sw/prod/R* | sort -rV | xargs -n1 basename); do
     found=$(find /dls_sw/prod/$v/support/*$PREFIX*BUILDER*/*/etc/makeIocs/ -name "$IOC_NAME.xml" 2>/dev/null | head -1)
     if [ -n "$found" ]; then echo "$found"; break; fi
   done
   ```

If not found, report and stop.

---

## Step 2 — Resolve support module paths from `_RELEASE`

1. Read the `_RELEASE` file alongside the XML:
   `<xml-dir>/<IOC-NAME>_RELEASE`

2. Determine the architecture from the XML `<components arch="...">` attribute
   (default to `linux-x86_64` if not specified).

3. Read the BUILDER's configure/RELEASE file to get macro definitions:
   - For work: `<BUILDER-root>/configure/RELEASE.<arch>.Common`
   - For prod: `<BUILDER-root>/<version>/configure/RELEASE.<arch>.Common`
   - Also check `configure/RELEASE` (no arch suffix) as a fallback

4. Substitute macros in each `_RELEASE` line to get absolute paths:
   - Common macros: `SUPPORT`, `WORK`, `EPICS_BASE`
   - Resolve recursively: `$(SUPPORT)` → the value from the RELEASE file

5. Filter out infrastructure entries that are not support modules:
   `EPICS_BASE`, `TEMPLATE_TOP`, `SUPPORT`, `WORK`

---

## Step 3 — Read and parse the XML

Read the XML file. Extract:

- Each element's tag (e.g. `tektronix.DPO2004B`), split into `module.class`
- All attributes on each element (these are the component arguments)
- XML comments — note commented-out elements as disabled components
- The `<components arch="...">` attribute if present

Group elements by support module.

**XML template entities (`auto_xml_*`)**: Some entities use classes like
`GIGE-BUILDER.auto_xml_GIGE_FIT_TEMPLATE_G158B`. These are XML template
expansions — a single element in the IOC XML that expands to multiple child
entities from other support modules. When you encounter an `auto_xml_*` class:

1. Locate the template XML file — it will be in the same `etc/makeIocs/`
   directory as the IOC XML, named after the template (e.g.
   `GIGE-FIT-TEMPLATE_G158B.xml`)
2. Read the template to see what child entities it expands to
3. In the report, list it as an XML template and note what it expands to
   (e.g. "Expands to: ADAravis.aravisCamera, ADCore.NDTransform, ...")
4. The child entities' support modules are the real dependencies

---

## Step 4 — Produce the report

Format the output as follows:

```
## IOC: <IOC-NAME>

**Architecture**: <arch>
**Source XML**: <full-path-to-xml>

### Support modules (from _RELEASE)

| Module | Version | Path |
|--------|---------|------|
| ethercat | 7-2 | /dls_sw/prod/.../ethercat/7-2 |
| rackFan | 2-12 | /dls_sw/prod/.../rackFan/2-12 |
| AUTOSAVE | 5-10-2 | /dls_sw/prod/.../AUTOSAVE/5-10-2 |

### Components

#### <module> (N entities)
- **<ClassName>** `<name-or-id>`: param1=value1, param2=value2
- **<ClassName>** x20: master=ECATM, type_rev varies (EK1100, EL3104, EL1014)
- **<ClassName>** x14: DEVICE=BL21I-VA-ERIO-*:MOD*, PORT=DCS*, SCAN="1 second"

#### <module2> (N entities)
- **<ClassName>** `<name>`: param1=value1, ...

### Disabled components (commented out)
- <module>.<ClassName>: name1, name2, name3, ...
```

Key formatting decisions:

- **Condense repetitive entries**: when there are many instances of the same
  class with similar arguments, show one full example and a count
  (e.g. "x20 EthercatSlave instances") rather than listing every one
- **List ALL support modules** from `_RELEASE`, including infrastructure ones
  (AUTOSAVE, UTILITY, etc.) — these give context about the IOC's dependencies
- **Show commented-out entries** in a separate "Disabled components" section,
  listing only the class and names/identifiers briefly
- **Identify the name/id** for each entity: use the `name` attribute if
  present, otherwise use the first attribute that looks like an identifier
  (e.g. `P`, `device`)
- **Show key arguments inline** for each entity, not as a full table — keep
  it scannable
