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
| `test_samples_were_generated_from_the_committed_pin` | samples predate either pin |

**Both read `git ls-tree HEAD`, so they fire once the pin is _committed_, not
while it is staged.** `git add` followed by pytest will report all-pass. CI only
ever sees committed state, so this is a local-only gap.

`make_samples.sh` records what it used in `tests/samples/GENERATED_AGAINST`.
Re-run it after any pin bump even when no sample output changes — the record
tracks the revisions built from, not whether the outputs differed.

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
