---
name: streamdevice-sweep
description: Sweep /dls_sw/prod for DLS support modules convertible to runtime StreamDevice patterns, decide eligibility mechanically, report the verdicts, and curate the documentation and ibek.manifest.yaml of an existing pattern folder in ibek-runtime-streamdevice. It does NOT create pattern folders or their ibek.support.yaml - that is separate work pending ibek#361. Use when asked to sweep dls_sw for runtime patterns, to decide whether a module can be a runtime pattern rather than a generic IOC, to refresh the docs of ibek-runtime-streamdevice against a newer DLS release, or to produce the build-time-only skip report. Work in progress — read its Status section first; its measured figures go stale and its output needs review rather than trust.
---

# Sweeping `/dls_sw/prod` into runtime StreamDevice patterns

A **runtime pattern** is a folder in
[ibek-runtime-streamdevice](https://github.com/epics-containers/ibek-runtime-streamdevice)
that an IOC instance vendors at a pinned version with `ibek pattern`. The generic
`ioc-streamdevice` image already ships StreamDevice; the pattern supplies only
the per-device protocol, database and `*.ibek.support.yaml`. **No image rebuild.**

That is the whole constraint: a module is convertible **only if it needs nothing
in the IOC binary**. Everything below follows from it.

Use with [vdct-conversion](../vdct-conversion/SKILL.md) (mandatory for
VDCT-authored databases), [ibek-concepts](../ibek-concepts/SKILL.md) and
[shared/builder-py-analysis.md](../shared/builder-py-analysis.md) (how to read a
`builder.py`), [shared/find-module-path.md](../shared/find-module-path.md) and
[shared/support-yaml-rules.md](../shared/support-yaml-rules.md).

> `/dls_sw` is a read-only fileserver. **Never run a broad `find`/`grep` over
> `/dls_sw`** — the scripts here walk only the latest release of each module and
> take about three and a half minutes in total. Do not hand-roll a wider scan.

## Status — work in progress

**This skill is unfinished and was merged in that state, deliberately, so the
work was not stranded on a branch. Treat its output as a starting point for
review, never as a decision you can act on unread.**

What has been exercised: the pipeline end to end produced the pattern library
now in `ibek-runtime-streamdevice`, and the eligibility gates were re-measured
against that library on 2026-08-05 (after #14 withdrew the 19 compiled-routine
patterns).

What to be careful of:

- **Every number here is a measurement, not an invariant.** The candidate counts
  (748 names / 186 with a protocol file), the verdict split (94 PASS / 67 SKIP /
  25 REVIEW), the 13 of 100 that fail a gate and the 19 description flags across
  9 folders were all measured on a specific day against a specific state of
  `/dls_sw/prod` and of the pattern library. They go stale the moment either
  moves. Re-run the scripts and re-measure rather than quoting these figures.
- **`REVIEW` means review.** The gates are deliberately conservative and a
  `REVIEW` verdict is not a soft `PASS`; 25 of 186 land there.
- The gate logic, the report grouping and the docs generation were each being
  corrected repeatedly right up to the merge, so treat edge-case behaviour as
  under-tested.

<!-- Extend this list as gaps are found. If you are picking this work back up,
     start by re-running the sweep and comparing against the figures above. -->

*The maintainer's own list of remaining work is not yet recorded here.*

## Run it

```bash
S=.claude/skills/streamdevice-sweep
bash $S/run-sweep.sh /tmp/sweep     # stages 1-3 and 8 only. ~3.5 min.
```

`run-sweep.sh` does the stages that are pure computation over `/dls_sw/prod`.
Sections **4–7** need judgement and are worked **per module**, not in bulk, and
section **9 is not run by any script** — it is the per-pattern validation that
has to pass before the PR goes up.

| § | What | How |
|---|---|---|
| 1 | candidate set + case-duplicate rule | `scan-candidates.py` |
| 2 | the three eligibility gates | `image-modules.sh`, `check-eligibility.py` |
| 3 | the skip report — a committed deliverable | `render-report.py` |
| 4 | VDCT conversion | [vdct-conversion](../vdct-conversion/SKILL.md) |
| 5 | documentation sweep | `sweep-docs.py`, `strip-images.lua` |
| 6 | the manifest, if and only if | `sweep-docs.py --apply` |
| 7 | entity models | [ibek-concepts](../ibek-concepts/SKILL.md) |
| 8 | description quality | `audit-descriptions.py` |
| 9 | validation before the PR | `ibek pattern add` / `check` |

`ibek-runtime-streamdevice`'s `main` already carries the restored VDCT hierarchy
(PR #12, `vdct-hierarchy-fix`, merged as `cc28c77`) and the two hand-cleaned
case-duplicates (PRs #11 and #13). Branch from `main`.

---

## 1. The candidate set

**Seed from modules containing a `.proto` or `.protocol` anywhere**, rather than
sweeping every module in `/dls_sw/prod` and rejecting most of them.

```bash
uv run --no-project python $S/scan-candidates.py -o /tmp/sweep
```

Measured on 2026-08-03: **748** module names across the eight `/dls_sw/prod/R*`
trees, **186** of them carrying a protocol file. That is the candidate set. All
100 folders currently in `ibek-runtime-streamdevice` are inside it, which is the
check that the seeding rule is not losing anything. (It was 119 before
ibek-runtime-streamdevice#14 withdrew the 19 patterns bound to compiled
`sub`/`genSub`/`aSub` routines; all 19 were inside the candidate set too.)

### Picking the release — neither `ls -t` nor `sort -V` is safe

A module lives under several EPICS trees. The rule, same as *Picking the release*
in [vdct-conversion](../vdct-conversion/SKILL.md): **the newest EPICS tree the
module appears in, then the highest version inside it**, with mtime only as a
tie-break.

Both of the obvious shortcuts are wrong, in opposite directions:

- **Newest mtime is not the latest release.** A back-port rebuilt after the
  release that supersedes it has the newer mtime and the older code.
  `keithley6517B 1-1-1` was rebuilt under `R3.14.12.3` in March 2019, four months
  after `1-2` was built under `R3.14.12.7`; `ETLdetector 1-20-1` was written five
  minutes after `1-21`; `ametekLockIn 1-6special2` six minutes after
  `1-17special2`. All three are PASS modules, so an mtime rule converts them from
  superseded sources and the docs provenance line names the wrong release.
- **A version sort is not safe either**, because version numbers restart:
  `fw102` was recreated as a lowercase module in 2023 and began again at `1.0`,
  so its highest version anywhere is a `2-2` built in 2015 under a tree it has
  since left. Picking the newest tree *first* is what makes the version
  comparison meaningful.

DLS version strings are not sortable by `sort -V` either, so `version_key()`
parses them: `-`, `.` and `_` are one separator (`gardasoftLED`'s `2.9` predates
`2-13`), digit runs compare numerically (`1-2` < `1-10`), a pre-release loses to
its release (`2-0beta1` < `2-0`) and a DLS patch beats it (`1-2-1` < `1-2-1dls3`).

**`Rx-y` is not a release.** It is the DLS build scratch directory — it holds the
build logs of whichever release was last built — and **48 modules have one**,
with an mtime that is often the newest of all. Any directory whose name does not
start with a number (`Rx-y`, `maketest`, `os_independant_test`) ranks below every
numbered release. Getting this wrong silently converts `CrateMonitor` from a 2018
scratch build instead of `2-4`.

Only five candidates are affected by any of this, and three of them are PASS.

### Case-duplicate modules — one device, two folders

`/dls_sw/prod` holds pairs differing only in case, because DLS renamed some
modules to lowercase and left the old directory behind. **Two folders differing
only in case collide on a case-insensitive clone** (macOS, a Windows
devcontainer), and `ibek pattern`'s `_clone_pattern` resolves a pattern by
`clone_dir / name`, so `ibek pattern add fw102` would silently pick up whichever
one landed. This is a correctness problem, not tidiness.

**Detection**: two candidate modules with the same name under `tolower()` are one
device.

**Which one is live** — the abandoned copy has a consistent signature:

| | live | abandoned |
|---|---|---|
| release count | many | exactly one |
| newest build | recent | old |
| shared release number | present | **same number, same date** as the live module's |
| EPICS versions | several `R3.14.*` trees | usually one |

The date match on the shared release is the strongest signal — it is the moment
the rename happened. "Newest build" here is the most recently built release of
any version — the question is whether this copy is still alive, which is not the
question `latest()` answers (that one is which release to convert from).

**Rule**: prefer the variant with more releases and the more recent build;
drop the other and record it in the skip report. **Decide on release evidence,
not on case** — lowercase winning is a consequence of the DLS convention, not the
rule.

Validated: the scan finds exactly three pairs in the whole of `/dls_sw/prod`.

| pair | winner | loser | shared release |
|---|---|---|---|
| `fw102` / `FW102` | `fw102` (9 releases, `2-1` 2025-07-17) | `FW102` (1, `1.0` 2023-05-09) | `1.0` @ 2023-05-09 — **the rename** |
| `belektronig_btc` / `BELEKTRONIG_BTC` | `belektronig_btc` (6, `2-2` 2021-06-04) | `BELEKTRONIG_BTC` (1, `2-0` 2019-10-15) | `2-0` @ 2019-10-15 — **the rename** |
| `Xspress3` / `xspress3` | **`Xspress3`** (42, `3-2-1` 2024-11-11) | `xspress3` (10, `1-11_i20_1` 2017-02-16) | none — independent histories |

The third is why the rule is release evidence and not case: here the
**capitalised** name wins, and the absence of a shared release/date correctly
says this is not a rename but an abandoned fork. It is still a case collision,
so it is still dropped, and the report says which signal was missing.

The first two are the ones that had to be cleaned up by hand
(ibek-runtime-streamdevice#11 and #13); the rule reproduces both decisions.

---

## 2. Eligibility — three gates, all must pass

```bash
bash $S/image-modules.sh /workspaces/ioc-streamdevice > /tmp/sweep/image-modules.txt
uv run --no-project python $S/check-eligibility.py --candidates /tmp/sweep/candidates.json \
        --image-modules /tmp/sweep/image-modules.txt -o /tmp/sweep/eligibility.json
```

Verdicts are `PASS` / `SKIP` / `REVIEW`. Measured: **94 PASS, 67 SKIP, 25 REVIEW**
out of 186.

### The reference set: read it from `ioc-streamdevice`'s Dockerfile

That Dockerfile **is** the truth about what the image ships — not `ibek-support`,
not this repo, not memory. `image-modules.sh` takes every `RUN ansible.sh <name>`
line, minus:

- **`--tags` runs** — a partial run is a build-stage tool, not a support module.
  This is what excludes `vdct` (it installs VisualDCT into the developer stage and
  registers nothing for runtime; see `ibek-support/vdct/README.md`).
- **`ioc`** — the generic IOC's own source.

Today that yields nine modules:

```text
StreamDevice  asyn  autosave  busy  calc  iocStats  pvlogging  sscan  std
```

`std` was added to unlock `keysightLCR`, `micos` and `tenmaPSU`, which were
blocked on it and nothing else; it also supplies the `epid` record type. It is
the only dependency worth adding — across all 186 candidates the only other
module that would unlock anything is `motor`, and that buys one device
(`microlab500`) at the cost of the whole asyn motor stack.

> **`image-modules.sh` reads the working tree**, so it answers for whatever
> branch is checked out. That is a real trap: scoring against `vdct-build-support`
> rather than `main` moves nine modules, because that branch adds `busy` and
> `sscan`. Record which ref the run used.

The script also **warns if `ARG DEVELOPER` points at another `ioc-*` image**: that
base's own module set is inherited and must be unioned in by hand. It currently
points at `epics-base-developer`, so the list above is complete.

> After the build-time management work lands in `ioc-streamdevice`, the truth
> moves to that repo's lock file. `image-modules.sh` is the one place that has to
> follow — everything downstream takes a plain list of names.

### Gate 1 — filesystem: no compiled code

No `*App/src/*.{c,cpp,cc,cxx}`, no module-authored `*App/src/*.dbd`, no SNL
`*.st`/`*.stt` (those are compiled in and need `seq`). `O.*` build directories are
excluded.

**One carve-out, or every module fails.** The DLS support-module template
(makeBaseApp) drops an *example IOC binary* into every module: `<mod>Main.cpp`,
the stock 20-line `iocsh(NULL); epicsExit(0)` main. **191 of the 245 `.cpp` files
under `*App/src` across the candidate set are that one file.** Excluding it by
**content** (`iocsh(` + `epicsExit(`, ≤4 KB, no function definition other than
`main`) rather than by name means a module that hid real code in a `*Main.cpp` is
still caught.

`<mod>_registerRecordDeviceDriver.cpp` is excluded too, but that carve-out is
defensive: it is generated into the `O.*` build directories, which are skipped
already, and matches **nothing** in the current corpus.

`fw102 2-1` is the calibration case: it has `fw102App/src/fw102Main.cpp` and a
`dbd/fw102.dbd`, and passes — the main is boilerplate and the dbd is built from
`base.dbd` in the *install* directory, not authored in `*App/src`.

### Gate 2 — `etc/builder.py`

`LibFileList` and `DbdFileList` empty or absent, and `Dependencies` a subset of
the image's module set.

`Initialise` / `PostIocInitialise` emitting st.cmd lines is **not** a
disqualifier: `ibek` expresses those as `pre_init`/`post_init` in the entity
model. With `LibFileList`/`DbdFileList` empty, anything a module emits must be
provided by a dependency, which this gate already covers.

Four things make this harder than a grep, and the script handles all four:

1. **`Dependencies` names classes, not modules.** `Dependencies = (Calc, AsynIP)`
   resolves through the import map: `from iocbuilder.modules.asyn import AsynIP`
   → module `asyn`. Names are matched case-insensitively against the image set
   with a tiny alias table (`streamDevice`→`StreamDevice`,
   `devIocStats`→`iocStats`).
2. **`iocbuilder.hardware` is not a module.** `from iocbuilder.hardware import
   (Seq, Busy, Calc)` imports from iocbuilder's *aggregate* namespace, into which
   every loaded module injects its exported names, so the import says nothing
   about which module a class came from. Reading it as a module called
   `iocbuilder` reports `Busy` and `Calc` — both of which the image ships — as
   not-in-image. The class name is resolved against the image set instead
   (`Calc` → `calc`), with a table for the classes whose name is not their
   module's (`AsynIP` → `asyn`). `insertionDevice` is the only candidate that
   uses this form, and it is `SKIP` on its `LibFileList` regardless; a module
   whose *only* dependencies arrived that way would have been skipped for a
   reason that was not true.
3. **A module-local dependency is usually benign.** `Dependencies = (HostLink,)`
   naming this builder.py's *own* class is only disqualifying if that class (or a
   base of it) carries `LibFileList`/`DbdFileList` — which gate 2 reports in its
   own right. Without this, `HostLink` and every module structured like it fails
   for no reason.
4. **16 of 160 `builder.py` files are python 2** (`print "x"`). They are repaired
   in memory (`print <expr>` → `print(<expr>)`) and re-parsed with `ast`; 158 of
   160 then parse. The remaining two fall back to a regex scan and are downgraded
   to `REVIEW`, never silently passed.

`ast` throughout, never `grep | sed` — the same trap as `Ident()` parsing in
[vdct-conversion §5](../vdct-conversion/SKILL.md).

### Gate 2 is not redundant with gate 1

Modules that pass the filesystem gate and are caught only by `builder.py`
(validated on this run):

| module | release | caught by |
|---|---|---|
| `jenaEDS` | `1-6` | `DbdFileList = ['jenaEDS']` — `*App/src` holds **only the boilerplate main**; the dbd it names lives in the install `dbd/` directory |
| `leyboldCenterOne` | `1-1` | `DbdFileList = ['leyboldCenterOne']` |
| `kriIonBeam` | `3-1` | `DbdFileList = ['kriIonBeam']` |
| `WS300scale` | `1-5` | `DbdFileList = ['WS300scale_vdct']` |
| `PIpiezo` | `1-23` | `DbdFileList = ['PIpiezo']` + `Dependencies = (MotorLib,)` |
| `microlab500` | `1-5` | `Dependencies = (MotorLib,)` — `motor` is not in the image |

(`micos`, `tenmaPSU` and `keysightLCR` used to sit in this table on
`Dependencies = (Std,)`. They now PASS: `std` was added to the image precisely
because it was the only thing blocking them.)

`jenaEDS` is the crispest: its dbd is installed from elsewhere in the tree, so a
filesystem-only gate admits it and the resulting pattern would not load.

### Gate 3 — the records themselves

Gates 1 and 2 judge what the **module builds**. Gate 3 judges what the **IOC
would have to resolve**, by reading every `*.template`, `*.db` and `*.vdb` under
the module's `db/` and `*App/Db/`.

Judge the module's databases **whole**, never an existing pattern's file set.
XMLbuilder synthesises an `auto_<name>` AutoSubstitution class for every
template, so the sweep takes them all — scoring a curated subset would pass a
module whose *other* templates carry records the image cannot resolve, and the
sweep would then vendor exactly those.

It rejects three things:

- **`sub` / `genSub` / `aSub` records.** They bind a compiled routine
  (`alarmlookupProcess`, `pfeifferErrorCodeParse`, `extractFirmwareVersion`), so
  they can never be vendored into an instance. Note that converting `genSub` to
  the base-7-native `aSub` does **not** help: the routine is still C compiled
  into the module's library. The two are one population at different stages of
  that conversion.
- **A record type the image does not provide** — `motor`, and anything outside
  base plus the record types the image's modules add (`calc` supplies
  `scalcout`/`sseq`/`acalcout`/`transform`, `busy` supplies `busy`, `std`
  supplies `epid`).
- **A `DTYP` the image does not provide** — `Hy8001`, `Hy8401ip`, `Hy8402ao`
  (Hytec IP-carrier hardware) as against `stream`, the soft-channel family and
  `asyn*`. A macro-supplied `DTYP` such as `$(DTYPE)` cannot be decided
  statically, so the module still `PASS`es and the macro is carried into the
  report as `instance_dtyp`. The pattern is vendorable; which device support an
  instance names is an instance question the sweep cannot answer. That is a
  flagged risk, not a cleared one — if an instance names anything but soft
  support, that support has to be compiled into its IOC. `currAmp`'s known
  consumer does not use the entity model in question at all and reads the device
  over Channel Access, which is why the flag beats a rejection here.

Gate 3 caught `jena`, `ozone` and `enzLoCuM4`, which pass both module gates and
still cannot run, and flagged `currAmp`'s instance-chosen `DTYP`.

### Gate 3 rescues gate 1, and never gate 2

If gate 1 fails but no database references the compiled thing, the rejection was
false — the module builds something the runtime never needs. That rescues
`attocube`, `SQC-310`, `ttiCPX`, `VatLeakValve590`, and the new `pilatus`,
`ThermoFHT6020A` and `epics-twincat-ads`.

**A gate 2 failure is never rescued.** A non-empty `LibFileList`/`DbdFileList` is
the module stating it needs its own library in the binary, and clean records
cannot contradict it: the dependency is usually an iocsh command emitted by
`Initialise()`, which lives in `st.cmd` and appears in no record. Rescuing over
gate 2 readmits exactly the modules `BUILD-TIME-ONLY.md` already rejects —
`PLV1000Config`, `centerNConfig`, `pmacAsynCoordCreate`, `YLRLaserConfig`. That
list is the regression test for this rule: no module named in it may come out
`PASS`.

### Two pre-gates

Applied before either gate, because they are about *what the module is*:

- **Already in the generic image** (`asyn`, `streamDevice`) — their `testApp`
  folders carry protocol files, so they seed as candidates. `SKIP`.
- **A beamline / facility module** (`BL21I`, `BL05I`, `BL15I-BUILDER`, `BR-LLRF`)
  — a collection of that beamline's IOC definitions, not a device. Its protocols
  belong to devices that have their own modules. `REVIEW`, not `SKIP`, because
  the name test is a heuristic and the rest of the sweep is not.

### `REVIEW` means a human decides

25 candidates have **no `etc/builder.py`** (14 of them also pass gate 1) and a
further **6 have one that defines no classes** — a two-byte file. Gate 2 is
vacuously satisfied in both cases, but there is no entity-model source to convert
from either, so they are reported and **never auto-passed**. The test is on
parsed content, not on the file existing: iocbuilder entities are classes, so a
`builder.py` with none declares no device.

Five of those six would otherwise be `PASS`, among them **`xspress3_api`** — the
Xspress3 detector's vendored C SDK, ~2000 `.c`/`.cc`/`.cpp` files under
`det-software/`, seeded into the candidate set by `det-software/docs/ife.protocol`,
which is a *prose description* of a network protocol and not a StreamDevice
protocol at all. It is the crispest argument for the rule: everything mechanical
about it says yes.

---

## 3. The skip report is a deliverable, not a diagnostic

**Commit the list of rejected modules with the reason for each — that list is the
backlog for the next phase of work.**

```bash
uv run --no-project python $S/render-report.py --outdir /tmp/sweep \
        --repo /workspaces/ibek-runtime-streamdevice > BUILD-TIME-ONLY.md
```

It replaces `BUILD-TIME-ONLY.md` at the root of `ibek-runtime-streamdevice` —
already the repo's name for this list, already linked from its README, and until
now hand-written and therefore partial. Generated, it covers all 186 candidates.

`eligibility.json`, `case-duplicates.json` and `descriptions.json` are all
**required** inputs: a report quietly missing a whole section is worse than no
report, so a missing one stops the render rather than shortening the file.
(`docs-skips.json` is optional — it accumulates per module as §5 is worked.)

Sections: the gate failures bucketed by cause; the case-duplicates; the ones
needing a human decision; the documentation that was not copied; the descriptions
that need writing; and:

### Already shipped as a pattern, but fails a gate

**13 of the 100 folders currently in `ibek-runtime-streamdevice` fail the
mechanical gates** — `LC400-OEM`, `PIpiezo`, `WS300scale`, `digitelMpc`,
`enzLoCuM4`, `jena`, `kriIonBeam`, `leyboldCenterOne`, `microlab500`, `mks937a`,
`mks937b`, `ozone`, `yaskawaBARTRobot`. They predate the gates, and they are now
all `DTYP`/record-type cases: the compiled-routine ones were withdrawn in
ibek-runtime-streamdevice#14.

**The sweep does not delete them.** It reports them, and each needs a decision:
trim the entity models that need the compiled support, move the pattern to a
build-time `ibek-support` definition, or record why it is acceptable. Deleting a
pattern breaks every instance pinned to it, which is not a call a sweep makes.

### The hand-written notes have to survive the next sweep

`BUILD-TIME-ONLY.md`'s existing final section ("Generated, but contains records
that reference non-stream device support") is the hand-written ancestor of this
one: eight per-module analyses no sweep can reproduce (`mks937a` →
`DTYP="$(aitype=Hy8401ip)"`, a Hytec 8401 IP ADC; `digitelMpc` →
`DTYP="ornlSerial"`; `LC400-OEM` → the npoint compiled array support).

The report is therefore **regenerated only above a marker**:

```text
<!-- hand-written notes below this line survive the next sweep -->
```

`render-report.py` reads that marker out of the existing `BUILD-TIME-ONLY.md` and
re-emits everything below it verbatim. **On the first run there is no marker**, so
the script says so on stderr and carries nothing over — move the existing
hand-written section below the marker by hand in that first commit
(`git show HEAD:BUILD-TIME-ONLY.md`), and it survives from then on. Anything
above the marker is regenerated and any edit there is lost.

---

## 4. VDCT

Where a module authors its databases in VisualDCT, conversion is **mandatory** —
there is no build step, so templates must already be native msi
`include`/`substitute`. Convert with
[vdct-conversion](../vdct-conversion/SKILL.md); do not re-derive any of it here.
In particular that skill's §4a covers the three things `vdct2template` gets wrong
**silently** (nested expansion losing the middle layer's `_` prefix; VDCT
instance-port references left as literal macros; a child that is also installed
standalone). Most of the modules needing it are already done
(ibek-runtime-streamdevice#12).

---

## 5. Documentation — the primary motivation

Docs live in a `docs/` subfolder of the pattern and are **never vendored into an
IOC instance**. They are repo context.

```bash
uv run --no-project python $S/sweep-docs.py --module /dls_sw/prod/R3.14.12.7/support/lakeshore340/2-6
uv run --no-project python $S/sweep-docs.py --module <dls-release> --pattern <repo>/<name> --apply \
        --skips-json /tmp/sweep/docs-skips.json
```

Plan mode classifies every file and names the `docs/` file it would write;
`--apply` converts, writes, prunes and maintains the manifest.

**`pandoc` is only needed when the plan actually converts something**
(`apt-get install -y pandoc`, or the static release tarball). Of the eight PASS
modules that produce a doc at all, four are pure markdown and need no pandoc, and
a re-sweep that only has a stale manifest to remove needs none either — which is
the case that maintains the docs↔manifest invariant, so it must not be gated on a
tool it does not use.

**Sweep set**: `README*` and `*.txt` at the module root, plus `documentation/`,
`docs/`, `doc/`.

**Convert to markdown** via pandoc (`.html`, `.rst`, `.odt`, `.docx`, `.tex`);
copy `.md` verbatim. Markdown throughout keeps the result maintainable.

**Except markdown that embeds figures**, which goes through pandoc as well. A
copy is byte-for-byte, so a `![fig](fig.png)` survives into a public repo as a
broken link pointing at artwork that was deliberately *not* copied — the one
thing the figure rule exists to prevent. Such a file is converted with the same
image filter and its provenance line says "Converted from"; plain markdown is
still copied and says "Copied verbatim from". No PASS module hits this today
(`asyn`'s README, with its two CI badges, is the corpus example).

**Two documents can want the same name.** `delaygen` has a root `README.md` (a
synApps pointer) and a `documentation/README.md` (the real DG645 notes), both of
which reduce to `docs/README.md`. Names are assigned across the whole plan, and a
collision falls back to the full relative path (`docs/documentation-README.md`)
for every file involved, so nothing is silently overwritten. Plan mode prints the
destination of each file for exactly this reason.

Two formats the issue's list does not name but the corpus contains:

- **DocBook `.xml`** (`documentation/UserGuide.xml`) — pandoc reads it natively
  (`--from docbook`) and it is often the best document in the module. Detected by
  a DocBook doctype or an `<article>`/`<book>` root.
- **Doxygen source pages** (`documentation/doxygen_pages`, `.dox`) — pandoc
  cannot read Doxygen markup. Classified `MANUAL`.

### The copyright blocklist — this repo is public

DLS `documentation/` folders routinely contain manufacturer datasheets and
manuals that **DLS has no right to redistribute**. Two arms, both mechanical:

| arm | rule |
|---|---|
| what a file **is** | `.pdf`, `.doc`, `.zip` (plus the rest of that class: archives, `.xls`, `.ppt`, `.exe`, …) and **every image format** |
| where a file **lives** | any path segment named `private`, `manufacturer`, `vendor`, `supplier`, `datasheet(s)`, `manual(s)`, `3rdparty` |

The path arm matters as much as the extension arm: `private/` is a live DLS
convention meaning exactly "third-party material"
(`lakeshore340/documentation/private/Manufacturer/Lakeshore/*.pdf`,
`mks647c/documentation/manufacturer/`). **Reference blocked files by name and part
number in the markdown instead, and report each skip** — `--skips-json`
accumulates them into the committed report.

**Strip image links** rather than copying figures. `strip-images.lua` is a pandoc
filter that drops every `Image` and appends a *Figures omitted* section naming
them. An honest gap beats a broken image link in a public repo.

### What is generated, and what is a stub

Two exclusions without which the sweep drowns:

- **Doxygen output.** 1494 of the 1566 `.html` files under `documentation/` are
  build output, alongside 1338 `.png`, 703 `.js` and 179 `.css`. Any path under
  `doxygen/`, `html/`, `latex/`, `search/`, `_build/`, `.svn/`, `.git/` is
  skipped.
- **The redirect stub.** DLS's `documentation/index.html` is usually a
  `<meta http-equiv="REFRESH">` pointing at the doxygen index. **66 of the 67
  HTML files left in the PASS set after that exclusion are that stub**, leaving
  exactly one real authored HTML document in the whole PASS set
  (`Keithley6487/documentation/devKeithley6487.html`). Detected by content.

### Curate, don't dump

Keep prose describing **the device, its PVs and the serial protocol**. Drop build,
release and site-configuration sections — "add to your `configure/RELEASE`", "add
`lakeshore340.dbd` to `src/Makefile`" — which are *actively misleading* in a
runtime-pattern context, where there is no build.

`lakeshore340`'s `documentation/doxygen_pages` is the worked example: a good
Introduction paragraph followed by four screens of exactly those instructions.
Keep the first, drop the rest.

**Skip basic READMEs with no relevant content entirely.** A docs folder that isn't
worth reading is worse than none. `.md`/text under 80 bytes is auto-skipped;
`DEVHISTORY.TXT`, `ChangeLog`, `LICENSE`, `CMakeLists.txt` and `Makefile` are on a
noise list.

### Calibration — expect a small yield

Of the PASS set (91 modules when this section was measured), **20 have any
authored document at all** and only **8
produce one automatically** (`Keithley6487`, `KeithleyDMM6500`, `alicatGasFlow`,
`attocubeInterf`, `enzLoCuM4`, `gardasoftLED`, `keithley2400`, `lakeshore340`);
the other 12 are `MANUAL` — a human reads them and decides. So **fewer than a
dozen patterns end up with a `docs/` folder** and 70-odd see no doc diff at all.
That is the expected outcome, not a failure, and it is what makes the
minimal-churn rule below cheap. 43 of those 91 have at least one file on the
copyright blocklist (125 blocked files in total), all of which are named in the
report rather than copied.

`fw102` is the calibration case at this end too: its `README.md` is **zero
bytes** and its `documentation/index.html` is a redirect stub. Correct outcome:
no `docs/`, no manifest, **folder untouched**.

### Provenance, and the generated marker

Each produced doc opens with a marker line and a provenance line — source module,
release, original filename — because vendored files no longer carry a header and
these are derived rather than pristine:

```markdown
<!-- generated by streamdevice-sweep -->

*Converted from `documentation/UserGuide.xml` in DLS support module `lakeshore340`
release `2-6` (`/dls_sw/prod/R3.14.12.7/support/lakeshore340/2-6`).*
```

The line states **only what the script did**. It does not claim the build and
site-configuration sections were dropped — that is curation, which happens
afterwards and by hand — and it does not claim figures were omitted from a file
that was copied verbatim. A header that describes work nobody has done yet is
worse than no header, and on a verbatim copy the old wording sat directly above
the very "set paths in `configure/RELEASE`" prose it claimed to have removed.

**Do not put the marker in a doc you write by hand.** It is what tells the next
sweep which files are its own: `--apply` **prunes** any marked file in `docs/`
that this release's plan did not produce, and then removes an emptied `docs/` and
its manifest. Without that, a re-sweep against a newer DLS release leaves the old
release's documents in place — attributed by their own provenance line to a
release the sweep no longer reads — and a renamed source file produces both the
old and the new copy side by side. Hand-curated documents carry no marker and are
never touched.

---

## 6. Minimise churn — the manifest rule

**A pattern gets an `ibek.manifest.yaml` if and only if it contains files that
must not be vendored** — today, that means it has docs.

**No docs ⇒ leave the folder exactly as it is.** No manifest, default behaviour,
all files vendored to `config/`. The flat root of protocol and template files
stays the common case, and the large majority of the 91 eligible folders see no
diff at all.

With docs, keep templates and protocol files in the pattern root and add a
single-entry manifest:

```yaml
version: 1
vendor:
  - src: '.*\.(template|proto|protocol|db|req|ibek\.support\.yaml|pvi\.device\.yaml)$'
    dest: config
```

`pvi\.device\.yaml` is **not** in issue #115's version of that regex. It is here
because the manifest is an allow-list — a file matched by no entry is not
vendored — and `ibek-runtime-streamdevice`'s README documents `*.pvi.device.yaml`
as an optional member of a pattern. No pattern carries one today, so leaving it
out costs nothing until the day someone adds one, at which point it stops being
vendored with no error at all (the other rules still match, so the empty-plan
guard never fires). "Anything else the support yaml references" cannot be
expressed as a regex; if a pattern grows something outside this list, extend it
in that pattern's own manifest.

`sweep-docs.py --apply` writes it when `docs/` ends up non-empty and **removes a
stale one** when it does not, so the invariant is maintained rather than
asserted. The manifest's presence then reads as a signal that a folder contains
something unusual.

Verified against the real implementation (`ibek.pattern_cmds.manifest.plan_vendor`
on the `pattern-manifest` branch): with `docs/UserGuide.md` present, the plan is
exactly

```text
config/lakeshore340.ibek.support.yaml
config/lakeshore340.proto
config/lakeshore340.template
```

Three details of that implementation to keep in mind:

- `src` is matched with **`re.fullmatch`** against the `/`-joined path relative to
  the pattern root. `ibek.manifest.yaml` itself is never vendored.
- A manifest whose rules match **no file** is a hard error, as is any unknown key
  and any `version:` other than `1`.
- **Keep the pattern root flat.** `dest: config` preserves nesting, so
  `sub/a.template` lands at `config/sub/a.template` — vendored and checked
  faithfully, but `ibek runtime place-files` copies `*.proto`/`*.template`/`*.db`
  into the IOC's search path from the **`config/` root only**, so it never gets
  placed at boot. A nested `*.ibek.support.yaml` is worse: ibek rejects the
  manifest outright, because `ibek pattern schema` merges
  `config/*.ibek.support.yaml` non-recursively.

Do **not** add `lock:`, `stamp:`, a per-pattern `root:`, or a `{pattern}` token to
`dest`. All were considered and rejected; `{pattern}` and `requires:` belong to
ibek#362 and are out of scope.

---

## 7. Entity models

Derive them as usual — [ibek-concepts](../ibek-concepts/SKILL.md),
[shared/support-yaml-rules.md](../shared/support-yaml-rules.md), and
[vdct-conversion §5](../vdct-conversion/SKILL.md) for the `auto_*` rule
(**everything in `db/`, minus files matching `^template() {`** — a `builder.py`-only
extraction silently misses most templates).

---

## 8. Self-documenting support yaml

We deliberately **do not** generate a README describing entity models —
`*.ibek.support.yaml` should be self-documenting, and generating one per pattern
would maximise churn across ~130 folders.

That only holds if the descriptions are real, so the sweep flags the ones that
are not:

```bash
uv run --no-project --with pyyaml python $S/audit-descriptions.py \
    --json /tmp/sweep/descriptions.json /workspaces/ibek-runtime-streamdevice
```

This is the one stage that needs a third-party import. `run-sweep.sh` runs it
with plain `python3` when that has `pyyaml` and falls back to the `uv` line
above when it does not — and **fails the whole sweep** if neither works, rather
than rendering a report with this section silently missing.

Flags a `description:` that is **missing, empty, a placeholder** (`TODO`,
`Description`, `-`), **too short**, or **trivially restates the name** (word set a
subset of the name's words plus filler). Measured: **19 flags across 9 of the 100
shipped patterns** — every one actionable, e.g. patterns whose `DESC` parameter is
described as "Description", and `kellerPyrometer` described as "Keller Pyrometer".

`object`, `entity`, `model` and `record` are deliberately **not** filler words:
they are ibek/EPICS domain terms, so `name: Object name` reads as the house idiom
rather than a restatement. Adding them to `FILLER` runs the audit strictly and
adds ~11 more flags.

The flags go in the report next to the skips.

---

## 9. Validation before opening the PR

**No script runs any of this** — `run-sweep.sh` stops at the report. Step 4 is the
only check that exercises the manifest through the real vendoring path, so a PR
opened without it has not verified the thing this work is for.

Per pattern:

1. `uv run ibek runtime generate2 <config-dir> --definitions <pattern>/<mod>.ibek.support.yaml -o <out> --no-pvi` — silence is success.
2. `msi -I. -S <out>/ioc.subst > expanded.db` then `grep -o '\$([A-Za-z_][^)]*)' expanded.db` — expect no output.
3. For a VDCT-derived pattern, the equivalence check against the DLS-built `db/`
   ([vdct-conversion §6c](../vdct-conversion/SKILL.md)).
4. `ibek pattern add <library>:<name>@<ref> <scratch-instance>` then
   `ibek pattern check <scratch-instance>` — this is what proves the manifest.
   `fetch_pattern` accepts a **local directory** as a library source, so point it
   at the working tree rather than a pushed branch.

Whole sweep:

- `BUILD-TIME-ONLY.md` regenerated and committed.
- Every folder that gained a `docs/` also gained a manifest, and no folder gained
  a manifest without one:
  ```bash
  for d in */; do
      d=${d%/}
      [ -d "$d/docs" ]; has_docs=$?
      [ -f "$d/ibek.manifest.yaml" ]; has_manifest=$?
      [ "$has_docs" = "$has_manifest" ] ||
          echo "MISMATCH: $d docs=$has_docs manifest=$has_manifest"
  done
  ```
- `git status` shows **no diff** for patterns with no docs and no VDCT change.
  A diff there means the sweep churned something it should not have.

### Two things to say in the PR body

- **Existing locks stop verifying.** `ibek pattern check` against a
  `runtime-lock.yaml` written before the vendored header was removed reports every
  file as missing and names `ibek pattern update`. That is by design (a lock whose
  hashes cover a header that no longer exists cannot verify anything), but
  consumers hit it the moment they take these patterns.
- **`ibek-runtime-streamdevice`'s README still describes the vendored header** and
  the "pristine, byte-for-byte" rule that VDCT conversion already broke. Update it
  in the same PR.

---

## Scripts

| Script | Does |
|---|---|
| `run-sweep.sh` | §1–3 and §8 end to end (~30 s). **Not §4–7, and not §9.** |
| `image-modules.sh` | gate 2's reference set, from `ioc-streamdevice`'s Dockerfile |
| `scan-candidates.py` | candidate set, latest-release pick, case-duplicate rule |
| `check-eligibility.py` | both gates; `PASS`/`SKIP`/`REVIEW` + reasons |
| `sweep-docs.py` | doc classification, pandoc conversion, provenance, pruning, manifest |
| `strip-images.lua` | pandoc filter: drop figures, list them instead |
| `audit-descriptions.py` | description-quality flags |
| `render-report.py` | renders the committed skip report, preserving its hand-written tail |

`check-eligibility.py --module <dls-release-dir>` runs the gates on one module,
which is the fastest way to answer "can this be a runtime pattern?" outside a full
sweep.
