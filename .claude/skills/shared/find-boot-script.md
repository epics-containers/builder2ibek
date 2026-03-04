# Find Original VxWorks Boot Script

How to locate the original VxWorks `.boot` file for an IOC, used when comparing
against the ibek-generated `st.cmd`.

## Algorithm

1. **Derive the beamline segment** from the IOC name — first two dash-delimited
   fields: `BL19I-VA-IOC-01` → `BL19I`

2. **List deployed versions**:
   ```bash
   ls /dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/
   ```

3. **Read the latest version's boot file**:
   ```
   /dls_sw/prod/R3.14.12.7/ioc/<BLXX>/<IOC-NAME>/<version>/bin/vxWorks-ppc604_long/<IOC-NAME>.boot
   ```
   (filename may also be `st<IOC-NAME>.boot` or similar — check the directory)

## Fallback

If the prod version is not found, check the in-progress builder version:
```
/dls_sw/work/R3.14.12.7/support/<BUILDER>/iocs/<IOC>/cmd/<IOC>.boot
```
