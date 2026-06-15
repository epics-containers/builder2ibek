# Find Module Path from _RELEASE

How to resolve a support module's absolute path from the IOC's `_RELEASE` file.

> **NEVER run a broad `find`/`grep` over `/dls_sw`** — it is enormous and
> hammers the fileserver. Always resolve the exact module path from a RELEASE
> file first, then open the one file you need (e.g. a specific `.template`).

## Quick path for the generic vacuum IOC

The generic vacuum IOC's RELEASE already lists every support module path:
```
/dls_sw/work/R7.0.7/ioc/BL/bl-va-ioc-01/configure/RELEASE
```
`grep DLSPLC ...` →  `DLSPLC = $(SUPPORT)/dlsPLC/<ver>-RTEMS`, with
`SUPPORT = /dls_sw/prod/R7.0.7/support`. Substitute to get the absolute path
and read the template directly (e.g.
`$(DLSPLC)/db/dlsPLC_temperature.template`).

## Algorithm

1. **Read the IOC's _RELEASE file** — located next to the XML:
   `<xml-dir>/<IOC-NAME>_RELEASE` (IOC-NAME is uppercase XML filename without
   extension, e.g. `BL21I-VA-IOC-01_RELEASE`)

2. **Read the BUILDER's configure/RELEASE** to get the `SUPPORT=` macro value:
   - Check `configure/RELEASE` first
   - Fall back to `configure/RELEASE.<arch>.Common` if needed

3. **Substitute macros** — replace `$(SUPPORT)` in each `_RELEASE` line with
   the resolved value to get absolute paths.

4. **Build a module → path table**, e.g.:
   ```
   ethercat → /dls_sw/prod/R3.14.12.7/support/ethercat/7-2
   rackFan  → /dls_sw/prod/R3.14.12.7/support/rackFan/2-12
   ```

## Fallback (no _RELEASE available)

If no `_RELEASE` file exists, discover the module version by listing:
```bash
ls /dls_sw/prod/R3.14.12.7/support/<module>/
```
Use the latest version directory.
