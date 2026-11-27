# Make a Hardware Status Screen

`builder2ibek hardware-status` writes a beamline's Phoebus hardware status
screen, the counterpart of the hand-drawn `BLxxX-hardware-status.edl` EDM
screen, from what the services repo deploys:

- one row per IOC instance in `services/`: ibek, dev-c7 or fastcs, plus any
  IOCs outside Kubernetes that you list
- a panel each for the GeoBricks, PLCs, RGAs, crate monitors and rack fans
  found in the entities of each ibek IOC's `config/ioc.yaml`

Every status widget is alarm sensitive, so a stopped IOC shows as
disconnected. The IOC and device buttons open the `index.bob` that each IOC
publishes on the opis server.

## The input file

Create `synoptic/hardware-status/hardware-status.yaml` in the services repo:

```yaml
title: I05 Hardware Status
# services whose names start with one of these are on the screen
beamline_services: ["bl05i-", "bl05j-"]

# services that are not IOCs, or not to be shown
skip:
  - bl05i-synoptic

# row labels, by IOC name; an IOC with no label shows its name only
labels:
  BL05I-MO-IOC-01: Motion (Main) S1, S2, S3, D3
  BL05I-VA-IOC-01: Vacuum (Main Line + ERIO)

# IOCs outside Kubernetes that belong on the screen; they run DLS iocStats,
# whose CPU load record is LOAD. One that is also in services/ shows once.
external:
  - name: BL05I-DI-IOC-01
    kind: vxWorks VME crate

# optional: the opis server root, relative to the screen (default ../..,
# for a screen published at <opis>/<service>/hardware-status/)
opis_root: ../..
```

`title` and `beamline_services` are required.

## Writing the screen

```bash
uv run builder2ibek hardware-status <path/to/services-repo>
```

writes `synoptic/hardware-status/hardware-status.bob` next to the input file.
Commit both, and re-run it whenever an IOC is added, split, renamed or
converted.

## What each row shows

| IOC | Name | CPU load | Autosave |
|---|---|---|---|
| ibek | from its `devIocStats.iocAdminSoft` entity, else the service name | `<IOC>:IOC_CPU_LOAD` | `<P>SR_status` of its `autosave.Autosave` entity |
| dev-c7 (`dev-c7:` in `values.yaml`) | the service name | `<IOC>:LOAD` | none |
| fastcs (`config/fastcs.yaml`) | the service name | none | none |
| external | from the input file | `<IOC>:LOAD` | none |

Every IOC with a CPU load LED also shows `<IOC>:UPTIME`.
