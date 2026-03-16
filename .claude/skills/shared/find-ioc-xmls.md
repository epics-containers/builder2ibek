# Find IOC XMLs for a Beamline

How to discover all IOC XML files for a given beamline.

## Algorithm

1. **Derive the BUILDER module name** — typically `<BLXX>-BUILDER` where
   `<BLXX>` is the beamline prefix (e.g. `BL19I-BUILDER`).

2. **Check work area first** (unreleased, most current):
   ```bash
   ls /dls_sw/work/R3.14.12.7/support/<BLXX>-BUILDER/etc/makeIocs/*.xml
   ```

3. **Fall back to prod** (released):
   ```bash
   ls /dls_sw/prod/R3.14.12.7/support/<BLXX>-BUILDER/*/etc/makeIocs/*.xml
   ```
   Use the latest version directory.

4. **Filter out template XMLs** — files containing `$(macro)` syntax are XML
   templates (used by `auto_xml_*` classes), not standalone IOC definitions.
   Skip these.

## Result

A list of IOC XML paths, one per IOC instance. Each can be passed to
`/ioc-convert` or `builder2ibek xml2yaml`.
