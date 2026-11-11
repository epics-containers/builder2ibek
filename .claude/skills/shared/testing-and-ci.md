# Testing and CI

How the test suite gets its inputs, and the guards that stop it lying to you.

**A green local run does not mean a green CI run.** The two environments differ
in ways that hide real failures — see [Reproducing CI](#reproducing-ci-locally).

## Where entity models come from

Both `update-schema` and `src/builder2ibek/support_defaults.py` glob
`ibek-support*/*/*.ibek.support.yaml` at the repo root. Only those files matter
to a test — nothing else in a module folder is read.

`ibek-support-dls` is on Diamond's internal GitLab, which GitHub Actions cannot
reach. `tests/vendored-support-dls/` holds a checked-in copy of the support
YAMLs the samples need (23 modules), and CI copies them into `ibek-support-dls/`
so every sample runs.

```bash
python3 tests/vendor_support_dls.py --check     # OK / PENDING / STALE
python3 tests/vendor_support_dls.py --update    # refresh from the submodule
python3 tests/vendor_support_dls.py --install   # populate ibek-support-dls/ (CI)
```

The vendored tree lives under `tests/` **deliberately**, so it does not match
the `ibek-support*` glob. A normal local checkout never sees it, and conversion
work uses the real submodule. `--install` refuses to touch an `ibek-support-dls/`
that already has content.

`--update` refuses unless the submodule is at the committed pin **and clean**:
the vendored files must correspond to a commit others can fetch, so an
uncommitted edit has to be pushed and the pin bumped first. If a skill has just
edited `ibek-support-dls/`, `--check` reporting `PENDING` is the expected
answer, not a failure. Report it; do not try to fix it.

## Runtime pattern libraries

`ibek-runtime-streamdevice` and `ibek-runtime-support` are submodules pinned at
**release tags**, because `ibek pattern add <library>:<pattern>@<tag>` clones by
git tag and `src/builder2ibek/patterns.py` takes the version from the tag the
checkout is at. A pin that is not on a tag is an error, not a fallback. Their
paths do not match `ibek-support*`, so `update-schema` never sees the pattern
models. CI clones both (they are on GitHub).

To take a new release: `git -C ibek-runtime-streamdevice checkout <tag>`, commit
the pin, then run `tests/test_patterns.py`. A release that aligns a pattern with
its generic model fails `test_alignment_matches_the_models` until the module moves
from `GENERIC_DIFFERS` to `ALIGNED` in `patterns.py`. That holds only with the real
ibek-support-dls checked out: with the vendored subset, most of those tests skip. `check_pin_freshness.py` warns when
a newer release tag exists. A pin bump changes the `@<tag>` in every
`tests/samples/*.patterns` and `*.runtime-lock.yaml`: run `make_samples.sh`.

### Library pins without submodules

`LIBRARY_VERSIONS` in `src/builder2ibek/patterns.py` repeats each library's
pinned tag, for an installed builder2ibek, which has no submodules: it clones
each library once at that tag into
`${XDG_CACHE_HOME:-~/.cache}/builder2ibek/patterns/<library>@<tag>` and indexes
and vendors from there. `test_library_versions_are_the_submodule_pins` fails
until a pin bump updates it. ibek keeps no cache of pattern libraries, only of
base schemas.

### Vendoring offline in the tests

`xml2yaml` vendors a pattern-only IOC with `ibek pattern add --source <local
library>`: the submodule, or the cached clone above. It then records the
library's GitHub URL as the lock's `source`, so a lock is the same whichever
copy it came from. ibek also fetches the image's published base schema. The
tests never touch the network: the session fixture `offline_patterns` in
`tests/conftest.py` (and `make_samples.sh` likewise) points `XDG_CACHE_HOME` at a
temporary folder, `IBEK_SCHEMA_CACHE` at a cache written by
`write_schema_cache()`, and `HTTPS_PROXY` at a dead port, so ibek falls back to
that cache.

The base schema of `DEFAULT_RUNTIME_IMAGE` (`src/builder2ibek/vendor_patterns.py`)
is part of the package, `src/builder2ibek/schemas/ioc-streamdevice-<tag>.json`,
the release asset `ibek.ioc.schema.json`. builder2ibek decides whether an IOC is
pattern-only from it with no network. Moving the image to a new tag needs that
tag's schema there (`gh release download <tag> -R epics-containers/ioc-streamdevice
-p ibek.ioc.schema.json`); `test_default_image_schema_is_packaged` fails until it
is, and `check_pin_freshness.py` warns when a newer image release exists.

A pattern sample (`BL08J-MO-IOC-13`) has two more golden files:
`<stem>.patterns`, the `--patterns-out` list, and `<stem>.runtime-lock.yaml`,
whose hashes pin every vendored file.

## After bumping a submodule pin

Two things must follow, and a guard catches each:

```bash
git submodule update --checkout ibek-support-dls   # match the committed pin
python3 tests/vendor_support_dls.py --update       # dls only
./tests/samples/make_samples.sh                    # both repos
```

| guard | fires when |
|---|---|
| `test_vendored_copy_records_the_committed_pin` | vendored copy predates the dls pin |
| `test_checkout_matches_the_committed_pin` | a checkout has drifted off the pin |

**Both read `git ls-tree HEAD`, so they compare against the _committed_ pin, not
a staged one.** Bump a checkout and the drift guard stays red until the gitlink
is committed — which is accurate: CI only ever sees committed state, so until
then a green suite says nothing about what CI will do.

There is no separate "samples are stale" guard, and none is needed.
`test_convert` and `test_generate` regenerate live from whatever is checked out
and compare against the committed samples, so a pin bump that changes any
output fails on the real diff. One that changes no output needs no regeneration
— re-running `make_samples.sh` for its own sake is busywork.

`vendor_support_dls.py --update` refuses to run while the checkout and the
committed pin disagree — it tells you to commit the bump first. So the order is:
commit the pin, vendor, then `--amend` the vendored files into that same commit.
Landing them separately leaves one commit that moves the pin without its
vendored copy, which fails the guard, so history contains a red commit.

### Regenerated samples must be reviewed by a human

**Never commit a regenerated sample set without the user reading the diff.**

The samples are the regression baseline for the whole converter: `test_convert`
and `test_generate` compare against them. Committing a regenerated set silently
redefines "correct", so a converter or support-YAML bug that changes `st.cmd` or
`ioc.subst` gets baked in as the new expected output and the suite goes green on
it. The diff **is** the review surface. Show it, explain what changed and why it
is expected, and commit only once the user has said so.

If a run fails partway, `git checkout -- tests/samples/` rather than committing a
partial or emptied set.

### make_samples.sh needs a writable `EPICS_ROOT`

`generate2` resolves entity models from `$EPICS_ROOT/ibek-defs`, which
`./update-schema` populates. Where `/epics` is read-only (some sandboxes),
`update-schema` cannot refresh it, so `generate2` validates every sample against
a **stale** schema, rejects them all, and `make_samples.sh` deletes all 14
outputs. The symptom is misleading — it names whichever support YAML sorts first
(`VALIDATION ERROR READING /epics/ibek-defs/ACCELCryoIP...`), which is not the
faulty file.

Point both steps at the same writable root, in one shell so it persists:

```bash
export EPICS_ROOT=$(mktemp -d)
./update-schema
./tests/samples/make_samples.sh
```

The same misleading symptom has a second cause: **two processes sharing one
`ibek-defs`.** `tests/conftest.py` also runs `./update-schema` into
`$EPICS_ROOT/ibek-defs` (default `/epics`), and `update-schema` does
`rm -f .../ibek-defs/*` before re-linking. Run `pytest` and `make_samples.sh` at
the same time — two terminals, or an agent alongside a human — and `generate2`
reads that window, fails on whichever file happens to be missing, and
`make_samples.sh` deletes that sample's outputs. The named module is innocent
and validates fine afterwards.

`conftest` guards *within* a session with an xdist file-lock, but nothing guards
across processes. If a single sample fails on a module unrelated to your change,
suspect this before believing it: re-validate the named file on its own, and
re-run with a private `EPICS_ROOT`.

`tests/check_pin_freshness.py` covers the opposite mistake: a pin that has *not*
moved while upstream has. It warns and never fails, and runs weekly from
`periodic.yml`.

## Reproducing CI locally

Two differences hide failures:

1. `/epics` exists here (pre-populated, read-only) but is **absent** on a
   runner. Anything resolving `ibek-defs` from the default `/epics` succeeds
   here and fails there.
2. Exporting `EPICS_ROOT` on the command line makes it worse: `subprocess.run`
   without `env=` inherits it, so child processes find definitions CI's children
   cannot.

```bash
env -u EPICS_ROOT uv run pytest -q
```

## Foot-guns

- **`make_samples.sh` deletes a sample's outputs when `generate2` rejects it**
  and keeps going, so a partial regeneration leaves files simply absent. It
  exits non-zero and names them at the end — do not ignore that.
- **A test that skips is not a test that passes.** An autouse fixture calling
  `pytest.skip` takes the whole session with it; this suite once reported
  success while running zero tests. `test_support_submodule_present` and
  `test_dls_models_available` exist to fail loudly instead.
- **Never compare a thing against itself.** The vendored drift guards skip
  unless `ibek-support-dls/.git` exists, because after `--install` that
  directory holds the vendored files and comparing them would pass while
  proving nothing.
