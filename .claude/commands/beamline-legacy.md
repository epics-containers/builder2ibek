---
argument-hint: <beamline-prefix> [<path/to/services-repo>]
description: Add every live Linux IOC of a beamline prefix to its services repo as a dev-c7 legacy IOC (phase 1 of a beamline migration).
---

# Beamline Legacy Workflow

Move every live Linux IOC with prefix `$1` (e.g. `BL08J`) into the cluster
as a **dev-c7 legacy IOC**. Each one runs the `/dls_sw` build its IOC server
boots today, unchanged, inside a RHEL7 container.

## The two phases

1. **dev-c7 for everything** (this command). Every live Linux IOC gets a
   `services/<ioc-name>/` folder made from `services/.legacy_ioc_template`.
   Its `values.yaml` holds a `dev-c7:` key that points at the IOC's existing
   build, so there is no conversion risk. Each folder is written with
   `global.enabled: false`. The cutover is **per IOC**: stop the IOC on its
   IOC server, or remove it from that server's `soft-iocs`, and only then set
   `enabled: true` and deploy its cluster copy. With hostNetwork, two running
   copies would serve the same PVs.
2. **ibek per IOC, when ready** (`/ioc-convert`). Converting an IOC finds the
   `dev-c7:` folder, deletes it and recreates it from `.ioc_template`
   ([CLAUDE.md](../../CLAUDE.md), `/ioc-convert` step 1a). Each conversion
   is one commit that replaces one legacy folder.

**Rollback** is a revert plus a restart. Reverting the phase 2 commit brings
back the IOC's dev-c7 folder. Reverting the phase 1 change (or setting
`enabled: false`) removes the cluster copy; then restart the IOC on its IOC
server (and restore its `soft-iocs` entry if it was removed).

This command only writes services-repo files. It never starts an IOC.

---

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../skills/shared/services-repo-resolution.md)
using `$2` (if provided) or the prefix `$1`. A J branch that shares its
parent's subnet uses the parent's repo, so `BL08J` goes in `i08-services`.
Tell the user which services repo is used.

## Step 2 — Dry run

```bash
uv run builder2ibek dev-c7 $1 --services-repo <services-repo>
```

The dry run prints one row per IOC with its action (`add` or `skip`),
version, source and the values it will write or the skip reason. Then it
lists notes, the server each IOC launches from, and the retired IOCs it
leaves out. Add `--json` for a machine-readable plan.

Where each piece comes from (read-only, on DLS NFS):

| Data | File | Format |
|---|---|---|
| Live IOCs | `/dls_sw/prod/etc/init/<server>/soft-iocs` | `IOC PORT [manualstart] [args]` |
| Live hardware IOCs | `/dls_sw/prod/etc/init/<server>/real-iocs` | `IOC HOST PORT` (console) |
| Version | `/dls_sw/prod/etc/redirector/redirect_table` | `IOC BOOT-SCRIPT`; the first match wins |
| Newest build (report only) | `/dls_sw/prod/<epics>/ioc/<PREFIX>/<IOC>/<ver>/bin/<arch>/st<IOC>*` | shown for IOCs with no redirect entry, and for work-area IOCs |

An IOC is live when a launch list names it. A redirect-table entry with the
prefix that no launch list names is retired: the report lists it and nothing
is written for it. A live IOC with no redirect entry cannot boot, so it is
skipped. Duplicate redirect entries and any launch arguments after the port
(e.g. a CA port) are shown in the notes.

Values written:

| Boot script | Values |
|---|---|
| `/dls_sw/prod/<epics>/ioc/<DOMAIN>/<IOC>/<ver>/bin/linux-x86_64/st<IOC>.sh` | `iocVersion`; `epicsDomain` when `DOMAIN` differs from `global.location`; `epicsVersion` when not `R3.14.12.7` |
| `<path>/<IOC>/bin/linux-x86_64/st<IOC>.sh` in `/dls_sw/work` | `iocPath: <path>`: it runs what runs today, and is flagged as needing a release |
| anything else under `/dls_sw/prod` or `/dls_sw/work`, or a `bin` folder with more than one `st*.sh` | `workingDir` and `args: [stdio-expose ./<script>]` (noted for review) |

The dev-c7 chart (2025.11.1) calls the location key `epicsDomain` and
upper-cases it. No per-IOC `securityContext` is written: `services/values.yaml`
shares one with every dev-c7 IOC.

Every new folder gets a top-level `global: {enabled: false}` with a comment
saying why, which renders `replicas: 0`. `--enable` writes enabled folders
instead, except for `manualstart` IOCs: procServ keeps those stopped until
someone starts them, so their cluster copy is always written disabled.

Skipped and reported: Windows, vxWorks and RTEMS IOCs, other non-x86_64
targets, Malcolm YAML entries, non-IOC services (EtherCAT scanners, Odin
processes), boot scripts outside `/dls_sw/prod` and `/dls_sw/work`, missing
boot scripts, live IOCs with no redirect entry, and IOCs that already have a
services folder (of any kind, including a dangling link).

## Step 3 — Review with the user

Show the plan. Call out:

- `work` rows: the IOC runs an unreleased build from `/dls_sw/work`. It keeps
  `iocPath`, and needs a release before its ibek conversion.
- `no (manualstart)` rows: normally stopped, so they stay disabled.
- duplicate redirect entries: fix the table; a duplicate breaks the boot on
  Linux.
- launch arguments: check the IOC doesn't need them in the cluster.
- non-standard entrypoints: check `workingDir` and `args`.

## Step 4 — Apply

```bash
uv run builder2ibek dev-c7 $1 --services-repo <services-repo> --apply
```

This writes the `add` rows. It checks every target first and writes nothing
if any of them exists, so it never overwrites a folder or half-applies; a
re-run skips everything it wrote before. Chart symlinks are copied as
symlinks. Hand-edit any value the user changed in Step 3, then leave the
commit to the user.

## Step 5 — Cut over one IOC at a time

For each IOC: stop it on its IOC server (or remove it from `soft-iocs`), set
`enabled: true` in its `values.yaml`, and deploy. Never enable a cluster copy
while the server copy can still run.
