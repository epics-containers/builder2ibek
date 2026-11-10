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
   build, so there is no conversion risk. Phase 1 **adds folders only**: the
   IOCs keep running on their IOC servers. Deploying is a separate, per-IOC
   cutover (Step 5) done outside builder2ibek.
2. **ibek per IOC, when ready** (`/ioc-convert`). Converting an IOC finds the
   `dev-c7:` folder, deletes it and recreates it from `.ioc_template`
   ([CLAUDE.md](../../CLAUDE.md), `/ioc-convert` step 1a). Each conversion
   is one commit that replaces one legacy folder.

> **Never deploy a legacy services folder while its IOC is running on its
> IOC server.** With hostNetwork, both copies would serve the same PVs.
> Either don't deploy the service yet, or deploy it and stop it at once
> (e.g. `ec stop <service>`). The plan output and the top of each written
> `values.yaml` repeat this warning.

This command only writes services-repo files. It never deploys or starts an
IOC, and it does not touch the deployment repo: under ArgoCD the deployment
repo alone decides what runs (it sets `global.enabled` for every service), so
a values-file flag in the services repo could not stop anything.

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

Each written `values.yaml` starts with a comment naming the IOC's server and
warning not to deploy while it runs there. `manualstart` IOCs (procServ
`-w --noautorestart`, normally stopped) are marked "manualstart: keep stopped
after deploying" in the plan and in that comment.

Skipped and reported: Windows, vxWorks and RTEMS IOCs, other non-x86_64
targets, Malcolm YAML entries, non-IOC services (EtherCAT scanners, Odin
processes), boot scripts outside `/dls_sw/prod` and `/dls_sw/work`, missing
boot scripts, live IOCs with no redirect entry, and IOCs that already have a
services folder (of any kind, including a dangling link).

## Step 3 — Review with the user

Show the plan. Call out:

- `work` rows: the IOC runs an unreleased build from `/dls_sw/work`. It keeps
  `iocPath`, and needs a release before its ibek conversion.
- `[manualstart: keep stopped after deploying]` rows: normally stopped on
  their server, so keep the cluster copy stopped too.
- duplicate redirect entries: fix the table; a duplicate breaks the boot on
  Linux.
- launch arguments: check the IOC doesn't need them in the cluster.
- non-standard entrypoints: check `workingDir` and `args`.

## Step 4 — Apply

```bash
uv run builder2ibek dev-c7 $1 --services-repo <services-repo> --apply
```

This writes the `add` rows. The plan is rebuilt from live NFS, so compare
the `--apply` output with the dry-run plan the user reviewed and raise any
difference. Every target is checked for existence (including a dangling
link) before any write, and nothing is written if one exists, so a folder is
never overwritten. An I/O error part way through can leave the folders
written so far; a re-run skips them. Chart symlinks are copied as symlinks.
Hand-edit any value the user changed in Step 3, then leave the commit to the
user.

## Step 5 — Cut over one IOC at a time (outside builder2ibek)

For each IOC, once the services commit is merged:

1. Stop the IOC on its IOC server (or remove it from that server's
   `soft-iocs`).
2. Deploy and start its cluster copy: `ec deploy` / `ec start`, or enable it
   in the deployment repo.

Never start a cluster copy while the server copy can still run.

## Rollback

1. Stop the cluster copy: `ec stop <service>`, or `enabled: false` for it in
   the deployment repo. Reverting the services commit alone does not stop a
   running Application.
2. Wait for the pod to go.
3. Restart the IOC on its IOC server (and restore its `soft-iocs` entry if
   it was removed).

For an IOC already converted in phase 2, reverting that commit brings back
its dev-c7 folder.
