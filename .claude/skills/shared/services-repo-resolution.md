# Services Repo Resolution

Resolve the services repo for an IOC using this priority order.

---

## 1. Explicit argument

If a services repo path is provided as an argument, use it directly.

## 2. Infer from IOC prefix

- Extract the first `-`-delimited segment from the XML filename:
  `BL11I-CS-IOC-09.xml` → `BL11I`
- Strip leading `BL`, separate digits and trailing letter(s):
  `BL11I` → digits=`11`, letter=`I` → beamline=`i11`
- Services repo name = `<beamline>-services`, e.g. `i11-services`
- Look for it at `/workspaces/<services-repo-name>/`

## 3. Fallback — cached path

Read `.claude/skills/ioc-convert/last-services-repo` if the inferred path
does not exist on disk.

## 4. If not found locally

Try to clone:
```bash
git clone git@gitlab.diamond.ac.uk:controls/containers/beamline/<name> /workspaces/<name>
```

If the clone fails (repo doesn't exist yet), create a minimal skeleton:
```bash
mkdir -p /workspaces/<name>/services/$IOC_NAME/config
```

## After resolution

- Tell the user which services repo is being used and how it was resolved
- Write the resolved path to `.claude/skills/ioc-convert/last-services-repo`
  (overwrite if present)
- Derive `IOC_NAME` = lowercase XML filename without extension
- `INSTANCE_DIR` = `<services-repo>/services/$IOC_NAME`
