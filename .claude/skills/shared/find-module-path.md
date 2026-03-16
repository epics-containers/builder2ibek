# Find Module Path from _RELEASE

How to resolve a support module's absolute path from the IOC's `_RELEASE` file.

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
