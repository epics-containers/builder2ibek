# The golden-file test model

builder2ibek's conversion tests follow the **golden-file** pattern (also called
*approval testing* or *characterization testing*). `tests/samples/` holds one
builder XML per IOC and, next to it, the output that XML produced the last time
someone reviewed it. The tests run the pipeline again and compare the new output
with those files.

## What is under test

```text
<IOC>.xml
  --(builder2ibek xml2yaml)-->     <ioc>.yaml                  <-- test_convert, test_generate
  --(ibek runtime generate2)-->    <ioc>.st.cmd + <ioc>.ioc.subst <-- test_generate
```

- **`test_convert`** runs `convert_file()` in-process and compares the
  `ioc.yaml` it writes with `tests/samples/<ioc>.yaml`. Output file names are
  the lower-cased XML stem.
- **`test_generate`** runs both steps as subprocesses, so no converter state
  leaks between samples. It compares the YAML again, then the `st.cmd` and
  `ioc.subst` that `ibek runtime generate2 --no-pvi` produces from it.
- **`test_compare`** is the `db-compare` baseline. It compares
  `SR03C-VA-IOC-01_expanded.db` (XMLbuilder's output) with `sr03c-va-ioc-01.db`
  and expects the report to equal the committed `compare.diff`.

All of these are in `tests/test_file_conversion.py` and `tests/test_compare.py`.
The golden files are the committed `*.yaml`, `*.st.cmd`, `*.ioc.subst` and
`compare.diff`.

## The model in one paragraph

A baseline is **not a frozen contract. It is the last output someone looked at
and approved.** A failing test does not mean the new output is *wrong*. It means
the output *changed*, and a person has to decide whether the change is good. The
tests catch **change, not wrongness.** When you are happy with a diff, you
regenerate the baselines and commit them, and they become the new approved
output.

This cuts both ways. A converter bug that was already there when a baseline was
committed is now *part of* that baseline, and the tests will defend it. To
check correctness, compare against XMLbuilder's own `_expanded.substitutions`,
not against a previous conversion. See
[verify-against-builder.md](https://github.com/epics-containers/builder2ibek/blob/main/.claude/skills/shared/verify-against-builder.md).

## Regenerate, review, commit

```bash
./tests/samples/make_samples.sh                      # every sample
./tests/samples/make_samples.sh BL19I-VA-IOC-01.xml  # just one
git diff tests/samples/                              # the review
```

`make_samples.sh` runs `xml2yaml` and `generate2` for each XML and rewrites the
outputs. A sample that `generate2` rejects has its outputs deleted and is
reported at the end, and the script exits non-zero.

**The diff is the review.** Committing a regenerated set changes what "correct"
means for the whole suite, so read every hunk and explain why it is expected
before you commit. If a run fails partway, restore the samples with
`git checkout -- tests/samples/` rather than committing a partial set.

`generate2` reads entity models from `$EPICS_ROOT/ibek-defs`, which
`./update-schema` builds. Run both in the same shell against a writable root,
and don't run `pytest` at the same time: both rebuild that directory.

```bash
export EPICS_ROOT=$(mktemp -d)
./update-schema
./tests/samples/make_samples.sh
```

## Pinned, forward-moving dependencies

The output depends on the entity models in the `ibek-support` and
`ibek-support-dls` submodules. Golden files only work against a **stable**
input, so both submodules are pinned to a reviewed commit and moved forward on
purpose. A pin bump that changes any output fails `test_convert` or
`test_generate`, and the resulting diff shows exactly what the bump changed. A
bump that changes nothing needs no regeneration.

`ibek-support-dls` is on Diamond's internal GitLab, which public CI cannot
reach. Rather than skipping the DLS samples, CI installs a checked-in copy of the
models they need from `tests/vendored-support-dls/`
(`python3 tests/vendor_support_dls.py --install`). Guards in
`tests/test_vendored_support.py` and `tests/test_submodule_pins.py` fail if that
copy or a checkout drifts from the committed pin, so every sample runs
everywhere.
The pin and vendoring workflow is described in
[testing-and-ci.md](https://github.com/epics-containers/builder2ibek/blob/main/.claude/skills/shared/testing-and-ci.md).

## `support_defaults.py` and reproducible output

During conversion, `xml2yaml` drops any parameter whose value equals the default
in the support YAML (`src/builder2ibek/support_defaults.py`). It finds the
support YAMLs by globbing `ibek-support*/*/*.ibek.support.yaml` **beside the
package root**. That only exists in a source checkout that has the submodules.

An **installed** builder2ibek (for example from PyPI, or via `uvx`) has no
submodules next to it, so nothing is stripped and its `ioc.yaml` is more
verbose. Both are valid, but they are not byte-identical. Baselines are
always generated from a checkout, so compare against them from a checkout
too.

## Background reading

- *Approval testing*: <https://approvaltests.com>. Emily Bache has several
  clear talks and articles on the workflow.
- *Golden files*: popularised in the Go community by Mitchell Hashimoto's
  "Advanced Testing with Go" talk.
- *Characterization tests*: Michael Feathers, *Working Effectively with Legacy
  Code*.

rtems-proxy applies the same model to its hybrid end-to-end tests. See its
[golden-file-tests.md](https://github.com/epics-containers/rtems-proxy/blob/main/docs/explanations/golden-file-tests.md).
