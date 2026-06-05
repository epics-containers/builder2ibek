# Module & Verb Rename Map (old DLS → epics-containers)

When converting a **raw IOC** (`/ioc-convert-raw`) the only structured record of
which support modules are in play is `configure/RELEASE`, which uses the **old
DLS module names**. The target `ioc.yaml` uses the **epics-containers module
names**, and crucially **some modules also renamed their IOC-shell config
functions** during the migration.

That second fact breaks the otherwise-reliable "grep the st.cmd verb across
`ibek-support*/` `pre_init`/`post_init`" lookup: if the verb itself was renamed,
the grep finds nothing even though the entity exists under a new name.

This table is the authoritative bridge. **Grow it whenever a conversion hits a
verb with no `pre_init` match.**

---

## How to use it

For each st.cmd config verb:

1. **Direct match first.** `grep -rl "<verb>" ibek-support*/*/*.yaml`. If exactly
   one entity's `pre_init`/`post_init` emits it, use that module+entity. No table
   lookup needed.
2. **On a miss, consult this table.** Find the old module from
   `configure/RELEASE` (the module that *defines* the verb in its old `builder.py`
   / startup snippet), look up its new module here, then pick the entity within
   the new module whose `pre_init` has the **same argument shape** (count + which
   args are quoted strings vs ints).
3. **If still unresolved**, the rename is new — resolve it manually (see "Adding
   an entry") and **append it here** so the next run is deterministic.

---

## How to grow it (adding an entry)

When you discover a new rename:

1. Confirm the new module folder exists in `ibek-support/` or
   `ibek-support-dls/`.
2. Read the new entity's `pre_init` to get the **new verb** and its arg order.
3. Read the old module's startup output (the original `st*.src` you are
   converting is the best evidence) to get the **old verb** and arg order.
4. Add a row below, plus an **arg-mapping note** if the positional order or
   semantics changed.

---

## Module name map

| Old DLS module (RELEASE) | New epics-containers module | Notes |
|---|---|---|
| `aravisGigE` | `ADAravis` | camera driver; **verb renamed** (see below) |
| `ADCore` | `ADCore` | unchanged; all `ND*Configure` verbs stable |
| `ADSupport` | `ADSupport` | build-only dependency; no entities |
| `ffmpegServer` | `ffmpegServer` | unchanged; verbs stable |
| `gdaPlugins` | _unresolved_ | confirm at conversion time — likely folded into `ADCore`/`ADUtil`; do not guess |
| `autosave` | `autosave` | `save_restore*` / `set_*restoreFile` → single `autosave.Autosave` |
| `devIocStats` | `devIocStats` | → `devIocStats.iocAdminSoft` |
| `pvlogging` | `pvlogging` | → `pvlogging.PvLogging` |
| `asyn` | `asyn` | unchanged |
| `busy` / `calc` / `utility` | same | usually pure db-template / build deps |

> Only rows with verified evidence are listed. Absence from this table means
> "not yet confirmed" — verify against `ibek-support*/` at conversion time, do
> **not** assume a 1:1 name.

---

## Verb rename map

| Old verb (st.cmd) | New verb (`pre_init`) | New module.entity | Arg mapping |
|---|---|---|---|
| `aravisCameraConfig(portName, cameraName, maxBuffers, maxMemory)` | `aravisConfig(PORT, ID, CACHING, MEMORY, 0, 1)` | `ADAravis.aravisCamera` | `portName→PORT`, `cameraName(IP)→ID`. `maxBuffers`/`maxMemory` are **not** carried as-is — the new entity uses `CACHING`/`MEMORY` params; recover `P`/`R`/`CLASS` from the `_expanded.db` (join on PORT) — `CLASS` defaults to `AutoADGenICam`. |

---

## Verbs that map straight through (no rename — for reference)

These resolve via direct `pre_init` grep; listed so a future maintainer does not
waste time re-confirming:

- `NDStatsConfigure`, `NDROIConfigure`, `NDStdArraysConfigure`,
  `NDProcessConfigure`, `NDOverlayConfigure`, `NDFileTIFFConfigure`,
  `NDFileHDF5Configure` → `ADCore.*`
- `ffmpegStreamConfigure`, `ffmpegFileConfigure`, `ffmpegServerConfigure`
  → `ffmpegServer.*`

---

## Boilerplate verbs → standard entities (not module config)

These are IOC-shell housekeeping, not driver instantiation. They map to standard
entities or are dropped — never matched against module `pre_init`:

| st.cmd verb(s) | Becomes |
|---|---|
| `cd`, `dbLoadDatabase`, `*_registerRecordDeviceDriver`, `iocInit` | dropped (ibek emits these) |
| `epicsEnvSet "EPICS_CA_MAX_ARRAY_BYTES", N` | `epics.EpicsCaMaxArrayBytes` |
| `epicsEnvSet "EPICS_TS_MIN_WEST", 0` | covered by `epics.EpicsEnvSet EPICS_TZ` |
| `save_restoreSet_*`, `set_pass*_restoreFile`, `set_*file_path`, `directoryWait` | one `autosave.Autosave` |
| `dbpf "<pv>", "<val>"` | runtime puts — usually captured by autosave/db defaults; preserve as `epics.dbpf`/`StartupCommand` only if functionally required |
| `tyBackspaceSet`, `putenv`, `ld`, `calloc`/`malloc`/`strcpy`/`strcat`, `< file`, bare `VAR = "..."` | IOC-shell / VxWorks housekeeping — drop unless the value feeds a standard entity |
| `STREAM_PROTOCOL_PATH = calloc(...) … strcat(...)` block | drop entirely — global protocol path handled by the standard `STREAM_PROTOCOL_PATH` env entity (per CLAUDE.md) |
| other unrecognised but required calls (e.g. `callbackSetQueueSize(N)`) | `epics.StartupCommand` |

---

## VxWorks serial & IP-carrier setup (kept as entities)

These configure VxWorks IP-carrier/serial hardware. The conversion **keeps**
them as real entities and runs the serial hardware **passed through** as
`/dev/tty*` — there is **no terminal server**. (A `terminalServer`/Moxa module
exists for devices that are genuinely network-attached, but that is unrelated to
physical `/ty` serial ports.) Verify parameter names against each module's
entity model — the carrier/vector/ipslot/channel bookkeeping is intricate.

| Old verb (st.cmd) | Entity |
|---|---|
| interrupt vector number (`192`, `193`, …) | one `epics.InterruptVectorVME` (`Vec1`, `Vec2`, …) **per distinct vector number**, in appearance order. Carrier vectors get a reserved `Vec` that **nothing references** (Hy8002 has no `interrupt_vector`) → defs > refs |
| `Hy8001Configure(card, slot, vec, …, scan, 0, invertin, invertout)` | `ipac.Hy8001` (`slot`, `interrupt_vector`, `scan`, `invertin`/`invertout` bools, `direction`) |
| `IPACn = ipacEXTAddCarrier(&EXTHy8002, "<slot> <intLevel> <vec>")` | `ipac.Hy8002` (`slot`=first token); `IPACn` is the carrier ref; `<vec>` dropped |
| `DLS8515Configure(cardid, IPACn, vec, "ty")` / `DLS8516Configure(...)` | `DLS8515.DLS8515` / `.DLS8516` (`carrier`=IPACn, `interrupt_vector`=vec). **`ipslot = cardid − 10·carrier.slot`** (model defines `cardid = 10·slot + ipslot`); `name` = `<carrier.name>Module<ipslot>` |
| `Hy8401ipConfigure(cardid, IPACn, ipslot, vec, …)` | `Hy8401ip.Hy8401` — `ipslot` is **explicit** (arg 3), equals `cardid − 10·carrier.slot` |
| `drvAsynSerialPortConfigure("<port>", "/ty/N/M", …)` | `asyn.AsynSerial` (`name`=`<port>`, `port`=`/dev/ttyNM` — deterministic `/ty/N/M`→`/dev/ttyNM` rewrite) |
| `DLS8515DevConfigure("/ty/N/M", baud, data, stop, parity, …)` | `DLS8515.DLS8515channel` (`card`=entity with `cardid`=N, `channel`=M); emit `baud`/`data`/`stop`/`parity` **only when non-default** `9600`/`8`/`1`/`N` |
| `HostlinkInterposeInit("<port>")` + `finsDEVInit("<name>.Hostlink", "<port>")` | FINS interpose/port entity bound to asyn `<port>` |
