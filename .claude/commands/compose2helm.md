---
argument-hint: <path/to/compose-services-repo>[/services/<name>] [<path/to/helm-services-repo>]
description: Port IOC instances from a docker-compose services repo (services-template-compose) to a Kubernetes/helm services repo (services-template-helm), bumping generic IOC images to their latest releases.
---

# Compose → Helm Services Conversion

Port the IOC instances defined in the compose-based services repo `$1` into the
helm-based services repo `$2` as `ioc-instance` charts, renaming them into the
target repo's domain and bumping each generic IOC image to its latest release.

`$1` may be either a whole compose repo (convert every IOC service in it) or a
single service folder (`.../services/bl01t-di-cam-01`).

**The `config/ioc.yaml` itself barely changes** — the same ibek entity list
runs under both orchestrators. Almost all the work is in the *service
wrapper*: `compose.yml` becomes `values.yaml` + two symlinks, and everything
compose expressed as env vars and bind mounts is supplied by the helm chart
instead.

---

## Step 1 — Pre-flight: is the target repo writable?

In the Claude sandbox `/workspaces` is mounted **read-only** except for an
allowlist of repos, so the target services repo is very often not writable.
Check before doing any work — the failure mode is a `mkdir: Read-only file
system` half way through:

```bash
mount | grep "on /workspaces/" | grep "(rw" | sed 's|.*on /workspaces/||; s| type.*||' | sort -u
```

If the target repo is **not** in that list, work in a clone instead:

```bash
git clone /workspaces/<target>-services /workspaces/builder2ibek/.worktrees/<target>-services
```

`.worktrees/` is already in builder2ibek's `.git/info/exclude`. Do the whole
conversion in the clone, commit it on a branch there, and tell the user how to
land it (widen `claude-sandbox.conf` and relaunch, or push the branch). Say up
front that you are working in a clone — do not silently redirect the output.

---

## Step 2 — Read both repos

### Source (compose) repo

```
services/<name>/compose.yml      # the service wrapper
services/<name>/config/ioc.yaml  # the ibek IOC definition
services/<name>/config/*.db      # optional extra soft records
include/ioc.yml, .env            # shared compose bits — helm equivalents are built in
```

An entry in `services/` is an **IOC** if its `compose.yml` extends
`service: linux_ioc` (from `include/ioc.yml`) *and* it has a `config/ioc.yaml`.
Everything else is an infrastructure service — see the table in Step 5.

### Target (helm) repo

Read, in this order:

- `.copier-answers.yml` → `domain`, `location`, `cluster_namespace`,
  `_commit` (the services-template-helm version).
- `services/values.yaml` → `global.domain`, `global.location`, and the
  `shared:` anchor merged into `ioc-instance:` (securityContext, hostNetwork,
  affinity, tolerations). **Anything set there must not be repeated per
  instance.**
- `services/.ioc_template/` → the skeleton every new instance copies. Match it
  exactly; it is the repo's own statement of what an instance looks like.
- `requirements.txt` → the pinned `ibek==<ver>` used by pre-commit and CI. Use
  that same pin for every `ibek` invocation below.
- `.pre-commit-config.yaml` and `ci_verify.sh` → what CI will actually check.

---

## Step 3 — Name the instances

Compose repos are usually the `bl01t` example beamline. The target repo has its
own domain, so **rename**: replace the source location prefix with the target
repo's `location`, and uppercase it for PV prefixes.

```
bl01t-di-cam-01  →  <location>-di-cam-01      (e.g. bl11t-di-cam-01)
BL01T-DI-CAM-01  →  <LOCATION>-DI-CAM-01
bl01t:A          →  <location>:A              (lowercase soft-record prefixes too)
```

Cross-check the target repo's `synoptic/techui.yaml` (`short_dom` / `long_dom`)
and any existing service folders — they show the naming already in use.

State the rename in the final report. If the user wanted the names kept
verbatim it is a `sed` away, but silently keeping `bl01t-*` in a `t11` repo is
wrong.

---

## Step 4 — Find the latest image for each generic IOC

`gh` is usually **not authenticated** in this sandbox — use the REST API.

1. Map the image to its repo: strip the registry path and the
   `-runtime` / `-developer` suffix.
   `ghcr.io/epics-containers/ioc-adsimdetector-runtime:2.11ec1`
   → `epics-containers/ioc-adsimdetector`.

2. List recent releases (newest first):
   ```bash
   curl -s "https://api.github.com/repos/epics-containers/<repo>/releases?per_page=10" \
     | grep -E '"tag_name"|"prerelease"|"published_at"' | paste - - -
   ```
   Pick the newest non-prerelease tag. **Do not sort the tags as versions** —
   these repos switch schemes (`2025.11.1` was published *before* `2.11ec1`,
   which is newer). Sort by `published_at`.

3. Verify the tag actually exists on ghcr before writing it into `values.yaml`
   (a GitHub release does not guarantee a pushed image):
   ```bash
   img=epics-containers/ioc-adsimdetector-runtime; tag=2.11ec4
   tok=$(curl -s "https://ghcr.io/token?scope=repository:$img:pull" \
         | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
   curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $tok" \
     -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
     "https://ghcr.io/v2/$img/manifests/$tag"      # want 200
   ```

Record old → new for every image; the report and commit message need it.

---

## Step 5 — Create the instance folder

```bash
cd <target-repo>/services
mkdir -p <name>/config
ln -sfn ../../.helm-shared/Chart.yaml  <name>/Chart.yaml
ln -sfn ../../.helm-shared/templates   <name>/templates
```

Both **must be symlinks** into `.helm-shared` — `ci_verify.sh` runs
`helm dependency update` / `template` / `lint` per service folder and needs a
chart there. Copy `config/ioc.yaml` (and any `config/*.db`) across and apply the
Step 3 renames.

### compose.yml → values.yaml

Almost everything in `compose.yml` is **dropped**, because the `ioc-instance`
chart supplies it:

| compose.yml | helm equivalent | action |
|---|---|---|
| `image:` | `ioc-instance.image` | **keep** — bumped per Step 4 |
| `environment: IOC_NAME / IOC_PREFIX / IOCSH_PS1` | chart injects from `.Release.Name` (`IOC_PREFIX` overridable via `prefix`) | drop |
| `volumes: ../../opi/auto-generated/<n>:/epics/opi` | `<domain>-opi-claim` PVC, `subPath: <name>` | drop |
| `volumes: ../../autosave/<n>:/autosave` | `<domain>-autosave-claim` PVC | drop |
| `volumes: ../../..:/workspaces` | devcontainer-only | drop |
| `configs:` + `file: ./config` | ConfigMap generated from `config/` | drop |
| `extends: linux_ioc`, `include: networks.yml` | chart | drop |
| `profiles:` (`test` / `deploy` / `devcontainer`) | no equivalent | drop |
| `<name>-dev` service on a `-developer` image | no equivalent | drop |
| `labels: version:` | chart/ArgoCD | drop |
| `security_opt: label=disable` | SELinux, podman-only | drop |
| `ports:` | only meaningful if a plugin really serves HTTP (e.g. `ffmpegServer`) | drop unless the entity is live in `ioc.yaml` |
| `restart:`, `stdin_open`, `tty` | chart | drop |

What is worth **adding** on the helm side:

- `resources:` — the chart defaults to `500m / 256Mi`. That is too tight
  for an areaDetector plugin chain moving megapixel arrays; compose had no
  limits at all, so an unchanged port will OOM. Raise it, and say why in a
  comment.
- `dataVolume:` — only if the IOC writes files. Default is already
  `pvc: true, hostPath: /data`, so **do not restate the default**; set
  `pvc: false` + `hostPath:` for a real beamline data mount.
- `securityContext:` — only if this instance differs from
  `services/values.yaml`.

Keep `values.yaml` minimal. Every key that repeats a chart or `shared:` default
is noise that later has to be re-reviewed.

### config/ioc.yaml

Set the header to the per-instance schema — `ibek pattern schema` rewrites
it in Step 6, and the pre-commit hook enforces it:

```yaml
# yaml-language-server: $schema=../ioc.schema.json
```

Keep `ioc_name: "{{ _global.get_env('IOC_NAME') }}"` — it resolves under both
orchestrators. Carry the entity list over as-is apart from the renames, but do
fix obvious defects rather than porting them: mismatched `P:` prefixes,
entities commented out in the source, a stale `description:`. List every such
fix in the report.

Only add `STREAM_PROTOCOL_PATH` (present in `.ioc_template`) if the IOC
actually uses StreamDevice. If it does, its support is **vendored**, not built
into the image — read
[ibek-pattern-vendoring](../skills/ibek-pattern-vendoring/SKILL.md) and use
`ibek pattern add <library>:<pattern>@<tag> services/<name>`.

---

## Step 6 — Generate `ioc.schema.json`

```bash
cd <target-repo>
uvx --python 3.13 --from ibek==<pin> ibek pattern schema services/<name>
```

This fetches the base schema published with the image's release, merges any
vendored/local `*.ibek.support.yaml` from `config/`, and rewrites the
`ioc.yaml` header.

**Soft-skip is normal.** Not every generic IOC publishes an
`ibek.ioc.schema.json` release asset — `ioc-motorsim` publishes none for any
release. ibek prints `Schema not found ... skipping schema generation` and
exits 0; there is simply no `ioc.schema.json` for that instance. Do not
downgrade the image to chase a schema, and do not hand-write one.

---

## Step 7 — Validate

Do all four. Steps 7a–7b are the real correctness checks; 7c–7d are what
CI runs.

### 7a. Validate `ioc.yaml` against the generated schema

```bash
uvx --python 3.13 --with jsonschema --with pyyaml python - <<'EOF'
import json, yaml
from jsonschema import Draft202012Validator
schema = json.load(open("services/<name>/ioc.schema.json"))
doc = yaml.safe_load(open("services/<name>/config/ioc.yaml"))
errs = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
print("errors:", len(errs))
for e in errs[:10]:
    print(" ", list(e.path), e.message[:200])
EOF
```

**When the image publishes no schema (Step 6 soft-skipped)**, build one locally
from the exact support models baked into that image — this is the only way to
validate such an instance:

```bash
# the image's ibek-support submodule SHA (list the PARENT dir: /contents/ibek-support
# returns the submodule's *contents*, not the gitlink)
curl -s "https://api.github.com/repos/epics-containers/<repo>/contents/?ref=<tag>" \
  | python3 -c "import json,sys
for e in json.load(sys.stdin):
    if e['name']=='ibek-support': print(e['sha'])"

# which modules are in the image: its Dockerfile's ansible.sh lines,
# plus those of the image in its 'ARG DEVELOPER=' base, recursively
curl -s "https://raw.githubusercontent.com/epics-containers/<repo>/<tag>/Dockerfile" \
  | grep -E "ansible.sh|ARG DEVELOPER"

# fetch each module's model at that SHA (always include _global/epics.ibek.support.yaml)
curl -sL -o <mod>.ibek.support.yaml \
  "https://raw.githubusercontent.com/epics-containers/ibek-support/<sha>/<mod>/<mod>.ibek.support.yaml"

uvx --python 3.13 --from ibek==<pin> ibek ioc generate-schema *.ibek.support.yaml --output local.schema.json
```

Sanity-check the downloads (`wc -c`) — a raw URL for a SHA that is not in
`epics-containers/ibek-support` returns a 14-byte `404: Not Found` body, and
ibek then fails with a confusing pydantic "Field required: module" error.

### 7b. Render `st.cmd` locally

Schema validation cannot catch a Jinja2 or `databases` error. With the same
support YAMLs from 7a:

```bash
uvx --python 3.13 --from ibek==<pin> ibek runtime generate \
  <target-repo>/services/<name>/config/ioc.yaml *.ibek.support.yaml \
  --output ./out --no-pvi
cat out/st.cmd
```

`--no-pvi` is required — pvi needs `*.pvi.device.yaml` files that only exist
inside the image. Outside a container `cd ""` and `dbLoadRecords /ioc.db` (the
unset `IOC` / `RUNTIME` env vars) are expected; anything else is a real defect.

### 7c. `helm template` / `helm lint`

`helm` is not installed in this sandbox. Fetch it into the scratchpad:

```bash
SP=$(mktemp -d)     # or this session's scratchpad directory
curl -sL -o $SP/helm.tgz https://get.helm.sh/helm-v3.16.3-linux-amd64.tar.gz
tar --no-same-owner -xzf $SP/helm.tgz -C $SP     # --no-same-owner: tar fails on uid 1000 otherwise
export HELM_CACHE_HOME=$SP/helmcache HELM_CONFIG_HOME=$SP/helmconf HELM_DATA_HOME=$SP/helmdata

cd <target-repo>
$SP/linux-amd64/helm dependency update services/<name>
$SP/linux-amd64/helm template services/<name> --values services/values.yaml --values services/<name>/values.yaml
$SP/linux-amd64/helm lint     services/<name> --values services/values.yaml --values services/<name>/values.yaml
rm -rf services/<name>/charts services/<name>/Chart.lock    # gitignored, but don't leave them
```

In the rendered output confirm: the ConfigMap carries **every** file from
`config/` (`ioc.yaml` *and* any `.db`); `IOC_NAME` / `IOC_PREFIX` /
`IOC_LOCATION` / `IOC_DOMAIN` are set; the opi/autosave/runtime PVC mounts are
present; `resources` match what you asked for. The
`found symbolic link in path: .../templates` warning is expected.

### 7d. Validate `values.yaml` against the repo's values schema

`.helm-shared/values.schema.json` sets `unevaluatedProperties: false`, so a
typo'd or chart-version-inappropriate key is a hard CI failure. Validate with a
resolver that follows the remote `$ref`s (the schema pulls the `ioc-instance`
and Kubernetes container schemas over the network):

```bash
uvx --python 3.13 --with jsonschema --with pyyaml --with requests python - <<'EOF'
import json, yaml, urllib.request, referencing
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
def retrieve(uri):
    with urllib.request.urlopen(uri, timeout=60) as r:
        return Resource.from_contents(json.load(r),
            default_specification=referencing.jsonschema.DRAFT202012)
schema = json.load(open(".helm-shared/values.schema.json"))
doc = yaml.safe_load(open("services/<name>/values.yaml"))
errs = list(Draft202012Validator(schema, registry=Registry(retrieve=retrieve)).iter_errors(doc))
print("errors:", len(errs))
for e in errs[:8]:
    print(" ", list(e.path), e.message[:200])
EOF
```

---

## Step 8 — Report (do not commit)

Per the project convention, **do not commit** unless you are working in a
throwaway clone (Step 1), where a branch commit is the hand-off artefact.

Report:

1. **Table of instances** — new name ← source name, image old → new tag.
2. **Rename decision** — the domain the names were moved into, and the evidence
   (`.copier-answers.yml`, `techui.yaml`, existing service folders).
3. **What was dropped** — the compose-only keys, so the user can confirm none
   mattered.
4. **Source defects fixed** — mismatched prefixes, dead entities, wrong
   descriptions.
5. **Validation results** — schema errors (expect 0), `st.cmd` rendered, helm
   template/lint clean, values schema clean; and explicitly name any instance
   whose image publishes no schema and how you validated it instead.
6. **Not done** — e.g. the new IOCs are not registered as `components` in
   `synoptic/techui.yaml`, so they will not appear on the synoptic.
7. **How to land it** — if you worked in a clone, the branch name and the two
   options (widen the sandbox allowlist and relaunch, or push the branch).

---

## Non-IOC compose services

Do **not** hand-port these; the helm template repo already ships equivalents
(created by copier, not by this command):

| compose service | helm equivalent |
|---|---|
| `gateway`, `pvagw` | `services/<domain>-epics-gateways` |
| `epics-opis` | `services/<domain>-epics-opis` |
| `phoebus` | none — a developer workstation client |
| (n/a) | `services/<domain>-epics-pvcs` — the opi/autosave/runtime PVCs |

If the target repo is missing one, tell the user to re-run copier rather than
writing it by hand. A compose IOC that is *not* built on `linux_ioc` (a fastcs
service, say) belongs in `.fastcs_ioc_template`, not here — flag it and stop.
