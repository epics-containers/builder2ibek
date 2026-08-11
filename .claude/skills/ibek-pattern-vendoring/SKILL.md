---
name: ibek-pattern-vendoring
description: Operational knowledge and foot-guns for the epics-containers `ibek pattern` runtime-support vendoring system — vendoring/check/restore mechanics, the strict integrity-check policy, and the pre-commit/CI/packaging traps. Use when working on ibek `pattern`/`runtime` commands, services-template-helm pre-commit hooks or ci_verify.sh, runtime-lock.yaml, or the t01/bl01 services repos.
---

# ibek pattern runtime-support vendoring

`ibek pattern add|update|check|restore|schema` vendors a runtime-support file-set
(`*.ibek.support.yaml` plus optional `.proto`/`.protocol`/`.template`/`.db`) from a
central library into `services/<instance>/config/`, prepending a deterministic
`# Vendored from <src>@<ver> — DO NOT EDIT` header and recording each file's sha256
in `services/<instance>/runtime-lock.yaml`. Libraries: `ibek-runtime-streamdevice`,
`ibek-runtime-support`. Shipped in **ibek 4.6.0** (`ibek pattern`, `ibek runtime place-files`).

## check / dirty semantics
- `ibek pattern check <instance>` → **exit 1** on any hash mismatch (drift).
- `--allow-dirty` (or `IBEK_ALLOW_DIRTY=1`) downgrades mismatches to *warnings*
  (exit 0). It also makes the CLI still print "vendored files match the lock" — misleading.
- A lock entry whose value is `DIRTY # <reason>` is tolerated **even without** the
  flag (handled by `is_dirty()` before the allow-dirty logic). This is the sanctioned,
  visible way to keep a deliberate edit to a vendored file.
- **Policy (this project): strict on every branch** — hooks/CI run `check` WITHOUT
  `--allow-dirty`. To diverge deliberately: mark the lock entry `DIRTY # <reason>`.
  To try a throwaway edit: `git commit --no-verify` and tolerate red branch CI
  (red doesn't block deploying the branch to a cluster).

## FOOT-GUN 1 — pre-commit / shell loops mask non-last failures
A `bash -c 'for x in …; do cmd "$x"; done'` exits with the status of the **last**
iteration only. A failing earlier item (e.g. an edited vendored file in a
first-sorting instance like `bl01t-di-cam-01`) is silently masked by any later item
that passes → hook reports "Passed". Compounded by pre-commit **hiding a passing
hook's stdout**, so even a warning is invisible. Always keep `|| rc=1` + `exit "${rc}"`
— never rely on the loop's own exit status. Current canonical shape scopes to the
*changed* instances via `pass_filenames: true`, mapping each path back to its folder:
```bash
bash -c '
  rc=0
  for i in $(printf "%s\n" "$@" | cut -d/ -f1-2 | sort -u); do   # changed instances, de-duped
    [ -f "${i}/runtime-lock.yaml" ] || continue
    uvx --python 3.13 --from ibek --constraints requirements.txt ibek pattern check "${i}" || rc=1
  done
  exit "${rc}"' ibek-pattern-check                               # $0 placeholder; files land in "$@"
```
Don't hard-code the ibek version in the hook: `--from ibek --constraints requirements.txt`
makes uvx resolve ibek to whatever `requirements.txt` pins (`==`, `>=`, **or** a `name @
git+…` direct ref — uv constraints honour all three), so `requirements.txt` is the single
source of truth and auto-tracks the DLS-GitLab requirements variant in those repos.
The old `shopt -s nullglob; for … in services/*/…` form (looping *every* instance on any
change) still works but is slower and floods errors/skip-noise from unrelated instances.
ioc-schema narrows `files:` to `config/ioc.yaml|ioc.schema.json|values.yaml`; pattern-check
keeps a broad `^services/` trigger so edits to DO-NOT-EDIT vendored files still fire. Both
add `exclude: ^services/\.` (skip the `.ioc_template` skeleton). A top-level `set -e`/`set
-xe` (as in `ci_verify.sh`) also avoids the mask — it aborts on first failure; the bug
bites loops *without* it.

## FOOT-GUN 2 — `>=` version specs exclude pre-releases
`ibek>=X` will NOT install a pre-release `Xb2` — pip/uv skip pre-releases unless the
specifier names one (or nothing stable satisfies it). During a beta window pin
`==Xb2` or `>=Xb2`; switch to `>=X` once the final is out. This is why an image with
`ibek>=3.3.4` pulled stable `3.3.7` (no `place-files`) instead of the `4.6.0` beta.
Verify with `uv pip install --dry-run "<spec>"` in a scratch venv.

## FOOT-GUN 3 — pre-commit partitions files across parallel workers
With `pass_filenames: true`, pre-commit runs the hook once per CPU-sized partition of the
file list (xargs-style), in parallel. It splits by *file*, so one instance's files can land
in different partitions and each partition's `sort -u` re-runs that instance → duplicate
work and duplicated output (obvious under `--all-files`). Fix: **`require_serial: true`** →
a single invocation with the whole list, so `sort -u` de-dupes globally and each instance
runs once. (pre-commit also chunks for ARG_MAX, but that only bites at hundreds of files.)

## FOOT-GUN 4 — surfacing a soft-skip without failing the commit
pre-commit hides a *passing* hook's output, so `ibek pattern schema`'s soft-skip (exit 0
when the base schema 404s, e.g. a beta image) is invisible. Write just that line to
`/dev/tty` (bypasses pre-commit's capture; shows even on a pass). Three traps, all verified:
- **bare `… | tee | grep > /dev/tty`** (no file arg) pipes everything into grep and sends
  *only* matches to the tty — the full output never reaches stdout/stderr, so on a real
  failure with no tty (CI) the pipe tears down and pre-commit shows a **blank** "Failed".
  Emit the full output as its **own** statement first (`printf "%s\n" "${out}"`), then warn.
- **`grep … > /dev/tty 2>/dev/null`** does NOT suppress the no-tty error: bash opens (and
  fails) `> /dev/tty` *before* applying the trailing `2>/dev/null`. Use group level:
  `{ … > /dev/tty; } 2>/dev/null || true`.
- **`[ -w /dev/tty ]`** is a false guard — `/dev/tty` is always present with `rw` perms, so
  the test passes even when `open()` fails (ENXIO, no controlling terminal).

## Other conventions
- **Merge library PRs with a merge commit, not squash**, so version tags stay
  ancestors of `main`. Watch tag-prefix consistency (`v0.1.0` vs `0.1.1`).
- **Pushing to `gilesknap/t01-services` needs the `../t01-gh` PAT** — the cached
  token lacks write. epics-containers repos push fine via the cached token:
  `GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper='!gh auth git-credential' push https://github.com/<owner>/<repo>.git <branch>`.
- Template source of truth is `services-template-helm` (`template/ci_verify.sh`,
  `template/.pre-commit-config.yaml`); services repos inherit changes via `copier update`
  of a **released tag** (not the branch tip).
- **copier is delta-based, not recopy.** `copier update` replays the *diff* between the
  old and new template versions onto the service repo. So a rendered file that has
  **diverged** from the template (hand-edits, or drift from an old template) is NOT
  silently healed — copier only re-renders it if the new template version actually
  *changes that file*. Consequence both ways: (a) if a file diverged but the template
  didn't touch it, `copier update` leaves the divergence — fix by overwriting from
  `template/<file>` or `copier recopy -f`; (b) once the template *does* change the file,
  `copier update` re-renders it and the divergence is replaced (verified: t01's diverged
  `ci_verify.sh` healed to byte-identical-to-template after a template-touching update).
  Drift diagnostic: `copier recopy -f --skip-tasks` on a throwaway clone, then diff.
  (Gotcha tracked in epics-containers.github.io issue #232.)
- **Library version pins move fast during a rollout — verify, don't trust notes.** ibek
  4.6.0 was *yanked* (broken `ibek pattern` CLI) and replaced by 4.6.1; the real floor
  became `ibek>=4.6.1`. Always `gh release list` / check PyPI for the live version rather
  than reusing a number from an earlier session.

## Consuming a pattern — image ibek floor, library map, schema, sim wiring
- **The IMAGE must bake ibek ≥ 4.6.1 to *consume* a pattern, not just the workstation.**
  `ibek pattern add` runs on the workstation and succeeds regardless; consumption happens
  at container start, where `ioc/start.sh` runs `ibek runtime generate2 config`, which only
  discovers vendored `config/*.ibek.support.yaml` on ibek ≥ 4.6.1. An IOC image built with
  older ibek silently fails to load the pattern **at boot** (not at `add`). Check the
  image's pinned floor in its `requirements.txt`: `ioc-streamdevice` pins `ibek>=4.6.1`;
  `ioc-adsimdetector` pinned `ibek>=3.3.1` and needed a rebuild + new tag before its image
  could consume patterns.
- **`name@<ver>` pins a GIT REF, not a GitHub Release.** `ibek pattern add` clones the
  library with `git clone --depth 1 --branch <ver>` (sources.py `_clone_pattern`). The
  pinnable version is therefore a git tag, which can diverge from Releases:
  `ibek-runtime-support` had git tag `v0.1.0` and **no** GitHub release;
  `ibek-runtime-streamdevice` had release `0.1.1`. Verify with `git ls-remote --tags <url>`
  / `git -C <clone> tag`, NOT just `gh release list`. (Reinforces the tag-prefix-drift
  warning above: `v0.1.0` vs `0.1.1` will break the pin.)
- **Library map** (defaults from sources.py `DEFAULT_LIBRARIES` → `github.com/epics-containers/<name>`;
  override via `--source <uri|path>` or `IBEK_PATTERN_LIBRARIES="name=uri,..."` — a fork is
  just `--source` a local clone path or the fork URL):
  - `ibek-runtime-support` → non-StreamDevice runtime entities. Pattern `detectorPlugins`
    has TWO entity_models — `gdaPlugins` (full GDA set; needs **ffmpegServer**) and
    `detectorPlugins` (light Ophyd set; **ADCore-only**). A stock `ioc-adsimdetector` image
    builds only ADSimDetector+ADCore (no ffmpegServer) → only the **light** model works.
  - `ibek-runtime-streamdevice` → per-device StreamDevice file-sets (proto+template+support;
    lakeshore340, …).
- **`ibek pattern add` regenerates `config/ioc.schema.json`** by fetching the *image's*
  published base schema (`<ioc-repo>/releases/download/<image-tag>/ibek.ioc.schema.json`)
  and merging the vendored entities in. If that tag/asset isn't published yet the schema
  step soft-skips → the editor flags the vendored entity as an unknown type. So a
  not-yet-published image tag breaks BOTH runtime consumption AND editor validation.
- **Compose-track sims need a sidecar, not localhost.** A StreamDevice IOC in the
  `docker compose` track joins the `channel_access` bridge and cannot reach a simulator on
  host `localhost`. Run the sim as a sidecar compose service on `channel_access` and point
  `asyn.AsynIP` at the service name (the lakeshore340 sim binds `0.0.0.0:<port>`).
