# Move a beamline's IOCs into Kubernetes as dev-c7 legacy IOCs

This tutorial takes every live Linux IOC of a beamline and adds it to the
beamline's services repo as a **dev-c7 legacy IOC**. It is phase 1 of a
beamline migration. We use the i08-1 branch beamline (prefix `BL08J`, services
repo `i08-services`) as the worked example.

After completing this tutorial you should be able to:
- plan the legacy folders for a beamline with `builder2ibek dev-c7` and read
  every row and note of the plan
- write the folders with `--apply` and open a merge request for them
- cut each IOC over to the cluster one at a time, and roll one back

:::{danger}
**Never run an IOC on its IOC server and in the cluster at the same time.**
IOCs in the cluster use hostNetwork, so two running copies serve the same
PVs. Cut over one IOC at a time: stop it on its IOC server first, then start
its cluster copy. See [](#cutover).
:::

---

## Why two phases

A beamline migration has two phases:

1. **Phase 1: dev-c7 for everything.** Every live Linux IOC runs unchanged in
   the cluster. Its services folder uses the dev-c7 legacy chart, which starts
   the IOC's existing `/dls_sw` build inside a RHEL7 container. Nothing is
   converted, so the IOC behaves as it does on its IOC server.
2. **Phase 2: ibek, one IOC at a time.** Each IOC is converted to an ibek
   `ioc.yaml` with `/ioc-convert` or `builder2ibek xml2yaml`. The conversion
   replaces the IOC's legacy folder in one commit, so rolling back a
   conversion is a revert of that commit.

Phase 1 moves the whole beamline into the cluster early, with no conversion
risk. Phase 2 then proceeds at whatever pace suits the beamline.

`builder2ibek` only edits the services repo. It never deploys or starts an
IOC, and it never touches the deployment repo. Under ArgoCD the deployment
repo alone decides what runs.

---

## Prerequisites

You need:

- **A clone of the beamline's services repo, on a branch.** For example:

  ```bash
  git clone https://gitlab.diamond.ac.uk/controls/containers/beamline/i08-services.git
  cd i08-services
  git switch -c bl08j-dev-c7
  ```

- **Read access to `/dls_sw`.** The plan reads the IOC servers' launch lists,
  the redirect table and the IOC builds from there. Nothing is written under
  `/dls_sw`.
- **builder2ibek installed**, in a version that has the `dev-c7` verb. See
  [](installation.md), and check with:

  ```bash
  builder2ibek dev-c7 --help
  ```

- **The right services repo for a branch beamline.** The letter after the
  beamline number picks the beamline: `I` is `i<NN>`, `J` is `i<NN>-1`, `K` is
  `i<NN>-2`, `B` is `b<NN>` and `C` is `b<NN>-1`. A branch (`J`, `K` or `C`)
  that shares its parent's subnet goes in the parent's services repo, because
  one services repo maps to one subnet and cluster. A branch with its own
  subnet has its own `<branch>-services` repo.

  i08-1 shares the i08 subnet, so `BL08J` IOCs go in `i08-services`. Their
  folders keep the branch prefix, for example `services/bl08j-mo-ioc-02`. If
  you are unsure which repo a branch uses, check which `*-services` repos
  exist under `controls/containers/beamline` on GitLab, and ask the beamline's
  controls team when neither exists.

---

## Run the dry run

From the top of the services repo clone:

```bash
builder2ibek dev-c7 BL08J --services-repo .
```

The dry run writes nothing. It prints the plan: one row per live IOC, then
notes, the servers each IOC launches from, the retired IOCs, and a warning.
Add `--json` to get the same plan as JSON.

Here is a short excerpt of the BL08J plan:

```none
dev-c7 plan for BL08J -> . (global.location: bl08i)
sources: /dls_sw/prod/etc/redirector/redirect_table, /dls_sw/prod/etc/init/*/soft-iocs, /dls_sw/prod/etc/init/*/real-iocs

IOC               ACTION  VERSION  SOURCE      DETAIL
BL08J-CS-IOC-01   add     1-0      redirector  iocVersion=1-0, epicsDomain=BL08J
BL08J-CS-IOC-02   add     0-1      redirector  workingDir=/dls_sw/prod/R3.14.12.7/ioc/BL08J/BL08J-CS-IOC-02/0-1, args=['stdio-expose ./start-ioc']
BL08J-DI-IOC-01   add     work     redirector  iocPath=/dls_sw/work/R3.14.12.7/support/BL08J-BUILDER/iocs
BL08J-EA-IOC-02   skip    -        redirector  Windows IOC (windows-x64)
BL08J-EA-IOC-09   skip    -        none        in launch list but no redirect entry, so it cannot boot
BL08J-ML-MALC-01  skip    -        redirector  Malcolm YAML definition, not an IOC startup script
BL08J-MO-IOC-02   add     1-1      redirector  [manualstart: keep stopped after deploying] iocVersion=1-1, epicsDomain=BL08J

notes:
  BL08J-CS-IOC-02: non-standard entrypoint: workingDir and args set, review
  BL08J-DI-IOC-01: runs from /dls_sw/work: needs a release
  BL08J-DI-IOC-01: newest prod build is 1-9
  BL08J-EA-IOC-09: newest build: none in /dls_sw/prod
  BL08J-MO-IOC-02: manualstart: keep stopped after deploying

launched from:
  BL08J-CS-IOC-01: <ioc-server> (soft-iocs)
  BL08J-EA-IOC-02: <ioc-server> (soft-iocs); <ioc-server> (real-iocs)
  BL08J-MO-IOC-02: <ioc-server> (soft-iocs, manualstart)

retired (in the redirect table, in no launch list), left out:
  BL08J-EA-IOC-04: /dls_sw/prod/R3.14.12.7/ioc/BL08J/BL08J-EA-IOC-04/1-1/bin/linux-x86_64/stBL08J-EA-IOC-04.sh

23 folder(s) to add (dry run; --apply writes them)
```

The excerpt shows a few rows; the full plan has a row for every live IOC,
which is where the count of 23 comes from. The real plan names each IOC
server. Read it all before you go on.

### Where each value comes from

The plan reads the same files the DLS IOC servers boot from:

| Data | File | Line format |
|---|---|---|
| Live soft IOCs | `/dls_sw/prod/etc/init/<server>/soft-iocs` | `IOC PORT [manualstart] [args]` |
| Live hardware IOCs | `/dls_sw/prod/etc/init/<server>/real-iocs` | `IOC HOST PORT` (the IOC's console) |
| Boot script and version | `/dls_sw/prod/etc/redirector/redirect_table` | `IOC BOOT-SCRIPT` |

An IOC is **live** when a `soft-iocs` or `real-iocs` launch list names it.
Its version comes from its boot script in the redirect table. The redirector
uses the first line for an IOC, and so does the plan.

### The columns

- **IOC**: the IOC name. Its services folder is the lower-case name.
- **ACTION**: `add` writes a folder on `--apply`; `skip` writes nothing.
- **VERSION**: the release the IOC boots today, `work` for a build in
  `/dls_sw/work`, or `-` for a skipped IOC.
- **SOURCE**: `redirector` when the boot script comes from the redirect
  table, `none` when the IOC has no redirect entry.
- **DETAIL**: for an `add` row, the values written into the `dev-c7:` block
  of `values.yaml`. For a `skip` row, the reason.

### The values written

The values depend on where the boot script lives:

- **A standard release** (`/dls_sw/prod/<epics>/ioc/<DOMAIN>/<IOC>/<ver>/bin/linux-x86_64/st<IOC>.sh`)
  gets `iocVersion`. It also gets `epicsDomain` when the domain differs from
  the services repo's `global.location`. Branch IOCs in a parent's repo
  always need it: `BL08J` IOCs in `i08-services`, whose location is `bl08i`,
  get `epicsDomain=BL08J`. A release built against an EPICS other than
  `R3.14.12.7` also gets `epicsVersion`.
- **A build in `/dls_sw/work`** gets `iocPath`, so the cluster copy runs what
  runs today. The notes flag it as `runs from /dls_sw/work: needs a release`
  and show the newest prod build. Release the IOC before its phase 2
  conversion.
- **A non-standard entry point** gets `workingDir` and `args` that point
  straight at the boot script. This covers a script with another name, such
  as `start-ioc`, and a `bin` folder with more than one `st*.sh`. The notes
  say `non-standard entrypoint: workingDir and args set, review`. Check that
  the folder and script are right.

No per-IOC `securityContext` is written: `services/values.yaml` shares one
with every dev-c7 IOC.

### Flags

- **manualstart**: the IOC's launch list marks it `manualstart`, so it is
  normally stopped on its server. The row and the notes say
  `manualstart: keep stopped after deploying`. Keep its cluster copy stopped
  too.
- **Launch arguments**: anything after the port in a launch list, such as a
  CA port, appears in the notes. Check the IOC doesn't need it in the
  cluster.

### Skips

A `skip` row writes nothing. The reasons are:

- **Windows, vxWorks or RTEMS IOC**, or any other target that is not
  `linux-x86_64`: these cannot run in an x86_64 RHEL7 container. A hardware
  IOC's target comes from its boot script, not from its launch list.
- **Malcolm YAML definition** or a **non-IOC service** (EtherCAT scanners,
  Odin processes): these are not IOC startup scripts.
- **Boot script outside `/dls_sw/prod` and `/dls_sw/work`.**
- **No redirect entry**: the IOC is in a launch list but cannot boot. The
  notes show its newest build in `/dls_sw/prod`, if any. Add a redirect entry
  first if the IOC is still needed.
- **Boot script missing**: the redirect table points at a file that does not
  exist.
- **Services folder exists**: the repo already has a folder for the IOC, of
  any kind (dev-c7 legacy, ibek or other), or a dangling link. It is never
  overwritten.

### Reporting

- **Retired IOCs**: a redirect entry with the prefix that no launch list
  names. They are listed at the end and left out.
- **Duplicate redirect entries**: when the redirect table has more than one
  line for an IOC, the notes give the line numbers. The plan uses the first,
  as the redirector does, but a duplicate breaks the boot on Linux. Fix the
  table.

---

## Apply

When the plan is right, write it:

```bash
builder2ibek dev-c7 BL08J --services-repo . --apply
```

For each `add` row, `--apply` writes one folder, `services/<ioc-name>/`, made
from `services/.legacy_ioc_template`:

- `Chart.yaml`, a symlink to the shared legacy chart, copied as a symlink
- `values.yaml`, the template's `values.yaml` with its `iocVersion`
  placeholder replaced by the values from the plan

Each `values.yaml` starts with a warning comment naming the IOC's server:

```yaml
# yaml-language-server: $schema=../../.helm-shared/values.schema.json
# WARNING: this IOC still runs on <ioc-server>. Stop it there first, then
# deploy and start this service: with hostNetwork both would serve the same
# PVs. If it has to be deployed before that, deploy it stopped (ec stop
# --commit bl08j-mo-ioc-02 immediately); both serve the same PVs for that
# short window. Manualstart: keep stopped after deploying.

dev-c7:
  # prod #######################################################################
  ...
  iocVersion: 1-1
  epicsDomain: BL08J
```

`--apply` never overwrites. It checks every target before writing, and
writes nothing if any of them exists. Running it again skips the folders it
wrote, as `services folder exists (dev-c7 legacy)`.

`--apply` builds the plan again from `/dls_sw`, which may have changed since
the dry run. Compare the plan it prints with the one you reviewed, and look
into any difference. Edit any value you decided to change during the review.

Then commit, push and open a merge request on the services repo:

```bash
git add services
git commit -m "Add BL08J IOCs as dev-c7 legacy IOCs"
git push -u origin bl08j-dev-c7
```

Merging the folders does not start the IOCs: they keep running on their IOC
servers until you cut each one over.

---

(cutover)=
## Cut over one IOC at a time

:::{danger}
**Stop the IOC on its IOC server first, then start its cluster copy.**
IOCs in the cluster use hostNetwork. Two running copies would serve the same
PVs, and clients could connect to either one. Never run both.
:::

Cut over one IOC at a time, once the services merge request is merged. For
each IOC:

1. **Stop the IOC on its IOC server.** The plan's `launched from` section and
   the top of its `values.yaml` name the server. Stop it there. Removing
   it from that server's `soft-iocs` stops it starting again, but does not
   stop a running IOC, so do both if it must not come back.
2. **Deploy and start the cluster copy:**

   ```bash
   ec start --commit bl08j-cs-ioc-01
   ```

   Or enable the service in the deployment repo. Use `--commit`: without it,
   `ec` only patches the live Argo Application, and the next sync from the
   deployment repo can undo the change.
3. **Check it.** Watch the pod start, read its log, and check that its PVs
   respond and that clients and OPIs work.

Then move on to the next IOC.

Two more rules:

- **Keep a manualstart IOC stopped after deploying.** It is normally stopped
  on its server. Deploying starts it, so stop it at once with
  `ec stop --commit <service>`, and start it only when someone needs it.
- **Deploying a service starts it.** If you must deploy one before its IOC
  is stopped on its server, stop it at once:

  ```bash
  ec stop --commit bl08j-cs-ioc-01
  ```

  Both copies serve the same PVs for that short window, so keep it short.

---

## Roll back an IOC

To move an IOC back to its IOC server:

1. **Stop the cluster copy:**

   ```bash
   ec stop --commit bl08j-cs-ioc-01
   ```

   Or set `enabled: false` for the service in the deployment repo.
2. **Wait for the pod to go.**
3. **Restart the IOC on its IOC server**, and restore its `soft-iocs` entry
   if you removed it.

Reverting the services commit alone does not stop a running Application.
Always stop the cluster copy first.

---

## Next: phase 2

Phase 2 converts each IOC to ibek, one at a time, with `/ioc-convert` or
`builder2ibek xml2yaml`. A conversion finds the IOC's `dev-c7:` folder,
deletes it and recreates it from `services/.ioc_template`, so each conversion
is one commit that replaces one legacy folder. Reverting that commit brings
the dev-c7 folder back.

To convert an IOC, see:

- [](convert-ioc-xml.md), a quick introduction to `xml2yaml`
- [](../how-to/convert-ioc-instance.md), the full conversion guide
- [](../how-to/after-beamline-convert.md), what to check after converting a
  beamline
