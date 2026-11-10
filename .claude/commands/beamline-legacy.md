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
   build. The beamline moves to the cluster in one step with no conversion
   risk.
2. **ibek per IOC, when ready** (`/ioc-convert`). Converting an IOC finds the
   `dev-c7:` folder, deletes it and recreates it from `.ioc_template`
   ([CLAUDE.md](../../CLAUDE.md), `/ioc-convert` step 1a). Each conversion
   is one commit that replaces one legacy folder.

**Rollback** is a revert: reverting the phase 2 commit brings back the IOC's
dev-c7 folder, and reverting the phase 1 commit removes the folder, so the
IOC returns to its IOC server.

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
| Live IOCs | `/dls_sw/prod/etc/init/<server>/soft-iocs` | `IOC PORT [manualstart]` |
| Live hardware IOCs | `/dls_sw/prod/etc/init/<server>/real-iocs` | `IOC HOST PORT` (console) |
| Version | `/dls_sw/prod/etc/redirector/redirect_table` | `IOC BOOT-SCRIPT`; the first match wins |
| Fallback version | `/dls_sw/prod/<epics>/ioc/<PREFIX>/<IOC>/<ver>/bin/<arch>/st<IOC>*` | the newest version, flagged `newest-build` |

An IOC is live when a launch list names it. A redirect-table entry with the
prefix that no launch list names is retired: the report lists it and nothing
is written for it.

Values written:

| Boot script | Values |
|---|---|
| `/dls_sw/prod/<epics>/ioc/<DOMAIN>/<IOC>/<ver>/bin/linux-x86_64/st<IOC>.sh` | `iocVersion`; `epicsDomain` when `DOMAIN` differs from `global.location`; `epicsVersion` when not `R3.14.12.7` |
| `<path>/<IOC>/bin/linux-x86_64/st<IOC>.sh` in `/dls_sw/work` | `iocPath: <path>` (noted, with the newest prod build) |
| anything else under `/dls_sw/prod` or `/dls_sw/work`, or a `bin` folder with more than one `st*.sh` | `workingDir` and `args: [stdio-expose ./<script>]` (noted for review) |

The dev-c7 chart (2025.11.1) calls the location key `epicsDomain` and
upper-cases it. Some template comments say `iocLocation`, but the chart's
schema has no such key and rejects unknown keys. No per-IOC `securityContext` is written: `services/values.yaml`
shares one with every dev-c7 IOC.

Skipped and reported: Windows, vxWorks and RTEMS IOCs, other non-x86_64
targets, Malcolm YAML entries, non-IOC services (EtherCAT scanners, Odin
processes), boot scripts outside `/dls_sw/prod` and `/dls_sw/work`, live IOCs
with no redirect entry and no build, and IOCs that already have a services
folder (of any kind).

## Step 3 — Review with the user

Show the plan. Call out:

- `newest-build` rows: the redirector doesn't know these IOCs, so the version
  is a guess.
- `work` rows: the IOC runs an unreleased build from `/dls_sw/work`. Ask
  whether to keep `iocPath` or pin the newest prod release.
- `manualstart` notes: in the cluster the IOC starts with the deployment.
- non-standard entrypoints: check `workingDir` and `args`.

## Step 4 — Apply

```bash
uv run builder2ibek dev-c7 $1 --services-repo <services-repo> --apply
```

This writes the `add` rows. It never overwrites a folder; a re-run skips
everything it wrote before. Chart symlinks are copied as symlinks. Hand-edit
any value the user changed in Step 3, then leave the commit to the user.
