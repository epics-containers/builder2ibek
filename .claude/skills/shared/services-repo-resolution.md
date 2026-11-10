# Services Repo Resolution

Resolve the services repo for an IOC using this priority order.

---

## 1. Explicit argument

If a services repo path is provided as an argument, use it directly.

## 2. Infer from IOC prefix

- Extract the first `-`-delimited segment from the XML filename:
  `BL11I-CS-IOC-09.xml` → `BL11I`
- Strip the leading `BL`, then split it into digits and a trailing letter.
  The letter gives the beamline name:

  | Letter | Beamline | Example |
  |---|---|---|
  | `I` | `i<NN>`, the main beamline | `BL11I` → `i11` |
  | `J` | `i<NN>-1`, a branch | `BL08J` → `i08-1` |
  | `K` | `i<NN>-2`, a second branch | `BL02K` → `i02-2` |
  | `B` | `b<NN>` | `BL07B` → `b07` |
  | `C` | `b<NN>-1`, a branch | `BL07C` → `b07-1` |

  Any other letter, such as `P` or `T`: ask the user.

### Branch beamlines (`-1`, `-2`)

A branch shares the parent beamline's services repo when it shares the
parent's subnet. One services repo maps to one subnet and cluster, so i08-1
IOCs go in `i08-services`. A branch with its own subnet has its own
`<branch>-services` repo, as `b07-1`, `i04-1`, `i13-1`, `i15-1` and `i20-1` do.

To decide, check which repos exist under `controls/containers/beamline` on
GitLab (read-only, e.g. `glab api --hostname gitlab.diamond.ac.uk
"groups/controls%2Fcontainers%2Fbeamline/projects?search=<branch>"`):

- `<branch>-services` exists → use it.
- Only `<parent>-services` exists → use the parent's repo. An IOC folder there
  keeps its own branch prefix, e.g. `services/bl08j-mo-panda-01` in
  `i08-services`.
- Neither exists, or the parent's repo already holds IOCs from a different
  subnet → ask the user. Don't create a new branch repo on a guess.

### Then

- Services repo name = `<beamline>-services` for a main beamline, or as
  decided above for a branch
- Look for it at `/workspaces/<services-repo-name>/`

## 3. If not found locally

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
- Derive `IOC_NAME` = lowercase XML filename without extension
- `INSTANCE_DIR` = `<services-repo>/services/$IOC_NAME`
