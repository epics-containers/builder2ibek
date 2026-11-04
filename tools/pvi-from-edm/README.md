# pvi-from-edm

Generates PVI for ibek support modules from their EDM screens: a
`*.pvi.device.yaml` per device and a `pvi:` section per entity, grouped and labelled
as the screen has them, so the `.bob` screens a Generic IOC builds show what operators
are used to.

A separate tool, not part of `builder2ibek`: it imports nothing from it, adds nothing
to its command line and is not packaged with it. It runs in the same environment
because it needs what `builder2ibek` already depends on (`ibek`, `pvi`, PyYAML).

It generates from the committed support YAML (`git show HEAD:...`), so a support repo
must be a git checkout. Its output only adds lines to that YAML.

To run it you need `uv`, git, and the `msi` of an EPICS base, given with `--msi` or on
`PATH`. Without `msi` a run goes on with a parser of the tool's own, and `audit` fails. On
real modules you also need released support modules and a base's `dbd` folder. The tool
knows no paths of its own. For its tests only `uv`; those that need `msi` skip without it.

## The classification adds friction, not protection

EDM screens hide some writes until a condition holds: a mode, a password, a state.
PVI screens have no such condition. So the tool moves those writes, the *gated* ones,
to one `Protected Controls` sub-screen per device.

**This adds friction and not protection.** It is one extra click. Every PV stays
writable by anyone who can reach the IOC, from that screen, from a client, or from any
other tool. **It never replaces IOC-side enforcement**: access security, interlocks and
hardware limits are what protect a machine, and this tool changes none of them.

**No one who knows the hardware has checked the classification.** It comes from record
names, descriptions and screen text, by rule and by reading, with no IOC running. Treat
every entry as a guess to review. A control marked `mode-only` may be dangerous, and one
marked `dangerous` may be routine.

A classification file is a list of entries, each with `module`, `entity`, `pv`, `class`,
`evidence` and `judged`:

| Class | Meaning | Where the write goes |
|---|---|---|
| `dangerous` | The screen warns of it, it asks for a password or engineering mode, or a rule or a reading of its name says it could affect plant | `Protected Controls`, gated on its screen or not |
| `unsure` | No evidence either way. A gated write missing from the file counts as this | `Protected Controls`, gated on its screen or not |
| `mode-only` | The gate only hides what does not apply: this hardware variant, this selected mode, the record's own `DISA` | Where the screen has it |
| `momentary` | EDM writes one value on press and another on release, gated or not | `Protected Controls`, both values in one panel; on `.PROC` the press only, as any write processes the record |
| `keep-on-main` | A site's decision that it must stay quick to reach, such as a stop | The device's first screen, whatever the rules say |

Other fields say how much to trust an entry: `names_only` (judged from names and labels
alone), `behind_dialog` (already behind a confirmation dialog, which stays, so only
classified), `password_gated` (EDM asks for a password first; PVI has no such gate),
`not_placed` (why a momentary PV has no widget). `judged` says who decided: `rule:*`, `read`,
`person`, or `hand-written` for what the author of a hand-written device put on `Protected
Controls`. To change one, edit its `class`, set `judged: person` so `classify` keeps your
edit, and sweep again. `classify` keeps the entries of hand-written folders as they are, and
`audit` holds those folders to them.

With no classification file every gated write counts as `unsure`, so all of them move.

A gate on a link gates what it opens: every write on a screen behind a gated related display is a
gated write, and if it would move then it moves, even from behind a confirmation dialog, with the
dialog's text kept as its label. The same goes for a root found by search when a screen beside it
opens that root through a gated link. A gated link to a device of its own can't do that, as that
device is reached other ways too: `audit` counts those.

## Usage

Run from the root of the repo, with `uv run`. The tests are the tool's own, apart
from the repo's:

```bash
uv run pytest tools/pvi-from-edm
uv run python tools/pvi-from-edm/pvi_from_edm.py --help
```

Try it on a made-up site, with one module, needing nothing beyond the above:

```bash
uv run python tools/pvi-from-edm/example/make_example.py pvi-from-edm-work/example

# generate and validate; a dry run writes nothing to a support repo
uv run python tools/pvi-from-edm/pvi_from_edm.py sweep --dry-run --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work

# classify the gated writes, then generate again to use the result
uv run python tools/pvi-from-edm/pvi_from_edm.py evidence --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work
uv run python tools/pvi-from-edm/pvi_from_edm.py classify --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work
uv run python tools/pvi-from-edm/pvi_from_edm.py sweep --dry-run --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work

# check it against the screens and the .bob files, and look at it: open pvi-from-edm-work/example/work/review/index.html
uv run python tools/pvi-from-edm/pvi_from_edm.py audit --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work
uv run python tools/pvi-from-edm/pvi_from_edm.py review --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work

# install in the support repo, and compare the two byte for byte
uv run python tools/pvi-from-edm/pvi_from_edm.py sweep --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work
uv run python tools/pvi-from-edm/pvi_from_edm.py check --config pvi-from-edm-work/example/pvi-from-edm.yaml --work-dir pvi-from-edm-work/example/work
```

On real support repos, here one public module of the submodules of this repo. Give your
own release root, base `dbd` folder and `msi`, or a settings file holding them. With no
settings, nothing is classified:

```bash
uv run python tools/pvi-from-edm/pvi_from_edm.py sweep --dry-run --repo ibek-support --repo ibek-support-dls --prod-root SUPPORT_ROOT --base-dbd BASE/dbd --msi BASE/bin/ARCH/msi --work-dir pvi-from-edm-work/real mks937b
```

| Subcommand | What it does |
|---|---|
| `sweep [folder ...]` | Generate and validate each module without PVI, and install what passes. `--dry-run` writes to no support repo. Named or not, each folder it generates is reset to its committed state first, removing untracked device files. It refuses a folder whose device files or support YAML have uncommitted changes it did not install itself: see below. Exit 1 if a module fails, an entity is lost, a folder named doesn't exist, or a full run finds two folders sharing a device name. |
| `check` | Compare a sweep's output with the support repos, byte for byte, and list anything else changed there. Reads them only. Exit 1 on a difference. Folders starting `_` are ignored. |
| `generate <module> ...` | One module that has its own `<overrides>/<module>.yaml`. `--write` also writes it to its repo, and refuses a folder with uncommitted changes as `sweep` does, unless given `--overwrite-uncommitted`. |
| `validate [folder ...]` | Validate again what a sweep generated. With `--upstream-root DIR`, validate the hand-written folders instead: see below. |
| `audit` | Check a sweep from the EDM screens and the `.bob` files rather than from what the generator says it did, including the writes behind a gated link. It holds hand-written folders that have been validated to their classification entries, and ends by listing what it did not check. Exit 1 on a failure. |
| `evidence` | Gather the facts on each gated write. |
| `classify` | Write the classification file from the evidence. Entries with `judged: person` stay. `--out` writes elsewhere. |
| `review [module ...]` | Pages drawing each EDM screen beside its generated `.bob`. |
| `survey [folder ...]` | Estimate a sweep: no validation, nothing written to a repo. |
| `dump-edl <file> ...` | Print a screen as rows sorted by coordinates. |

Each module is checked with a test IOC instance made from its entity's parameters:
`ibek` `generate2` and `generate` must agree, a `.bob` must appear, and `msi` must expand
the result so every PV can be compared with the records the IOC would load. An entity that
fails is left out, with its reason in `sweep-status.json` and in the summary at the end of the
run. Six rounds that each find a new failure fail the module, and nothing is installed.

### Uncommitted changes

`<status-dir>/installed.json` holds a checksum of every file a sweep installed. A device file
or support YAML that differs from its commit and from that checksum is someone's work, so a
sweep leaves that folder alone and fails it. `--overwrite-uncommitted` loses those changes. A
dry run writes nothing, so it warns instead. Another `--work-dir` has no record of the files, and
reads everything uncommitted as someone's work.

### What a run says went wrong

A sweep ends with a summary: modules failed and entities lost, each with a reason, and
warnings. Something a site knows it will lose goes in `expected_losses`, with why, so it does not
fail the run; it is still printed. An entry names the class of failure the summary prints, and
`matches`, if given, is text the reason must hold: any other failure of that folder or entity still
fails the run. No entry excuses a timeout, a refused folder, a crash (`tool_exception`, `exception`,
`validator_error`, or a `TypeError` and the like in a reason), a change to a support YAML beyond its
`pvi:` sections (`yaml_changed`) or a `public_hygiene` hit, and the settings refuse one that lists
those classes. An entry for a folder no repo has is reported.

A version warning means `install.yml` builds one version and validation read another. It does
not fail a run. `accepted_versions` silences a difference once someone has looked at it, and warns
again if either version moves. `install_placeholders` lists `version` values that name no release:
with those, or with none, the newest release is validated and the summary lists the module.

### Hand-written folders

A sweep skips the `hand_written` folders and `check` lists them as skipped. Validate them
from the repo as they stand, against upstream rather than a release, with:

```bash
uv run python tools/pvi-from-edm/pvi_from_edm.py validate --upstream-root CHECKOUTS --config ... --work-dir ...
```

`CHECKOUTS/<folder>` is a checkout of the module at the version its `install.yml` builds: this
tool neither clones nor checks out, but it warns when the checkout is at another commit or has no
such version to compare, and when `msi` refuses a `.substitutions` file. `accepted_versions` (with
the checkout's short commit as `validated`) and `accepted_msi_refusals` silence one that has been
looked at. A public folder with none fails; any other falls back on its
release. Each checkout is laid out as a release under `<work-dir>/upstream-build` as its Db
Makefile would, with `msi`, and read from there. Of two files with one name, one in an App's `Db`
folder wins, then a top `db` folder, and test and example folders come last; two equally good and
different are reported. Each entity then has the checks above, and the
records it loads that no signal uses go in `validate.json`, and for a public folder in
`left-out.json` with a reason. Only a helper's record type gives a reason; any other record says
that none was recorded. `sweep` rewrites that file, so run this after it.

`<overrides>/<folder>.sweep.yaml` holds what such a folder needs:

```yaml
upstream_deps: [ADCore]         # other checkouts its templates include, under CHECKOUTS
upstream_build: prebuilt        # .db files under CHECKOUTS that a plain msi cannot make
test_values:                    # a value of its own, where a stand-in loads other records
  ThingWithChannels: {NCHANS: 16}
```

A device file included or extended from another folder is found in the repos, however deep.

## Options

All subcommands take these. Paths given here beat the settings file.

| Option | Default | Purpose |
|---|---|---|
| `--repo [KEY=]FOLDER` | none, required | A support repo folder, repeatable. Its key defaults to the folder name, and `repo:` in an override names it. |
| `--config FILE` | none | The settings file below. |
| `--prod-root`, `--work-root`, `--older-root` | none; a generating run needs one | Release roots, repeatable, in order of preference. |
| `--msi` | `PATH` | With none found, a parser of the tool's own is used, and `audit` fails. |
| `--base-dbd` | none; a generating run needs it | EPICS base's `dbd` folder, where record types' fields are defined. |
| `--support-dbd-glob` | none | Where any other record type's fields are defined, with `{}` for the type. |
| `--edm-colors` | none | An EDM `colors.list`, for review pages only. |
| `--classification` | none | The classification file. |
| `--classify-rules` | none | Rules judged by reading, for `classify`. |
| `--overrides` | none | Per-module inputs. |
| `--collisions` | none | A JSON list of device file names no sweep may use. |
| `--work-dir` | `./pvi-from-edm-work` | Parent of the next four. |
| `--output-dir`, `--sandbox-dir`, `--review-dir`, `--status-dir` | `<work-dir>/out`, `/sandbox`, `/review`, `<work-dir>` | Where the tool writes. |

### Settings file

Everything specific to a site lives outside this folder, and a run reads it by argument.
Every key is optional, and a relative path is relative to the file:

```yaml
repos: {public: ../ibek-support, internal: ../ibek-support-site}
public_repos: [public]              # device files here must not match hygiene_pattern
hygiene_pattern: '\w+\.example\.org'
prod_roots: [/releases/support]     # also work_roots, older_roots
last_resort_modules: [ADCore, asyn] # answer templates included by bare name
release_aliases: {stats: devStats}  # a folder whose releases go by another name
msi: /epics/base/bin/msi            # also base_dbd, support_dbd_glob, edm_colors
classification: classification.yaml
classify_rules: classify-rules.yaml
overrides: overrides
collisions: stem-collisions.json
hand_written:                       # a sweep never touches these folders
  - {repo: public, folder: stats}
forks:                              # generated once, installed in both
  - {repo: public, folder: thing, twin_repo: internal, twin_folder: thing_site}
reserved_stems:                     # device file names no other folder may take
  - {stem: thing, repo: public, folder: thing}
held_label_screens: [copied.edl]    # screens whose offLabel is a copy: use onLabel
expected_losses:                    # lost and known: a run still exits 0, and prints them
  - {folder: thing, entity: odd, class: test_instance, matches: "'items' is undefined", reason: its template needs a list no stand-in supplies}
  - {folder: other, class: no_screen_match, reason: its screens address none of its records}
accepted_versions:                  # checked, and not to warn until either side moves
  - {folder: thing, install: 3.3.0, validated: 3-2-1, reason: the records are the same}
accepted_msi_refusals:              # a .substitutions file msi may refuse, in a checkout
  - {folder: thing, file: EXAMPLE_x.substitutions, reason: nothing loads it}
install_placeholders: [SOMEBUILD]   # install.yml versions that name no release
```

### Overrides

`<overrides>/<folder>.yaml` pins a folder: its `repo` and `release` are fixed there rather
than found, and it may carry `devices`, with `subst`, `skip_links`, `link_labels`, `signal_labels`,
`extra_screens` and `judgements` per device, `entities`, with the `screen` and `macros` an entity's
root is, and `skip_entities`. `<overrides>/<folder>.sweep.yaml` adds any of those, `no_field_records`
or `test_values` to a normal sweep. Each is a judgement and gets reported. `signal_labels` gives
labels by element name, and a name matching nothing stops the run.

### Classification rules

`classify` applies the rules in `classify.py`, by warning text, password gate and name,
and the file named by `--classify-rules`, for what was judged by reading a site's modules.
`read` entries come before the mode-only rules, `read_last` entries after them, and
`engineering_gates` name the gates of an engineering mode. See `site_rules()` in `classify.py`.

## Limits

- A device with a field PV such as `X.PROC` has no `pv: true`: pvi writes a record name
  `softIocPVA` rejects. No generated section has `pv: true`, so these devices get a `.bob` and
  no PVI PV.
- A password on an EDM screen has no equivalent here. Writes it guarded are on `Protected
  Controls` with no password.
- Generated labels come from where text sits on a screen, and some will be wrong.
- No generated screen has been checked by a person against running hardware.
- `review` has no EDM screen to set beside a hand-written folder. It lists them, with the result of
  validating each, and their `.bob` files are in the sandbox folder.
