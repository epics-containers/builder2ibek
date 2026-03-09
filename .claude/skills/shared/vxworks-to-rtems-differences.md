# Expected VxWorks → RTEMS differences

These IOCs are being migrated from VxWorks to RTEMS using ibek/epics-containers.
The following differences between the original VxWorks boot script and the
ibek-generated `st.cmd` are expected and should **not** be flagged as problems.

| Original (VxWorks) | Generated (ibek/RTEMS) | Notes |
|---|---|---|
| Serial port paths `/ty/40/0` etc. | `/dev/tty400` etc. | VxWorks → RTEMS device path convention |
| `DLS8515DevConfigure(port, baud, ...)` for every port | `asynSetOption` only for non-default settings | Asyn defaults to 9600/8/1/N; only overrides needed |
| `STREAM_PROTOCOL_PATH = calloc/strcat(...)` with absolute prod paths | `epicsEnvSet STREAM_PROTOCOL_PATH /epics/runtime/protocol/` | ibek-managed protocol path |
| `ErTimeProviderInit`, `installLastResortEventProvider`, `syncSysClock` | Not present | VxWorks timing calls; not needed on RTEMS |
| `ld < bin/...munch`, `dbLoadDatabase "dbd/..."` | `dbLoadDatabase dbd/ioc.dbd` | VxWorks binary load replaced by standard dbd load |
| `asSetFilename` with absolute prod path | `/epics/support/pvlogging/src/access.acf` | ibek-relative path |
| `taskDelete(taskNameToId(...))` | Not present | VxWorks-specific housekeeping |
| `dbLoadRecords "db/..._expanded.db"` | `dbLoadRecords /ioc.db` | ibek-standard single db file |
| VxWorks autosave paths and `create_monitor_set` with `.req` file names | ibek-standard autosave setup | Normal translation |
