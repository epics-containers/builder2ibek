# Why one IOC instance touches eight repositories

Converting a single IOC is fast. Getting the result into a state where it can
actually run is not, and the difference is worth understanding before you plan
a beamline conversion.

This page uses one real conversion — `BL15I-VA-IOC-02`, August 2026 — as a
worked example. The specifics will date; the shape of the chain is the point.

```{raw} html
<!-- A literal href: a Markdown link to a file under _static/ gets rewritten
     into a _downloads/<hash>/ copy, which lives at a different depth and so
     breaks the chart's link back to this page. -->
<div class="admonition tip">
<p class="admonition-title">The same material as a one-page chart</p>
<p><a href="../_static/one-ioc-eight-repos.html"><strong>One IOC, eight
repos</strong></a> maps the dependency graph, the eleven forced steps and the
friction inventory visually, on a single page. It is the better starting point
if you are presenting this or skimming it; this page carries the analysis and
what it suggests we change.</p>
</div>
```

## The short version

The conversion itself took seconds and produced correct output: 338 XMLbuilder
elements became 335 ibek entities, with every entity type round-tripping. Ten
defects then had to be fixed across six support modules in three repositories,
a fourth repository had to cut a release, and the chain stopped twice waiting
for a human to merge a request.

None of that work was avoidable and none of it was wasted — every fix benefits
every IOC that uses the same module. But almost all of it was *discovered* by
running the conversion, rather than known in advance.

## The dependency graph

Support metadata sits three tiers below the thing you are trying to build.

**Tier 1 — support metadata.** `ibek-support` (public, on GitHub) holds
community entity models. `ibek-support-dls` (on Diamond's GitLab) holds the
DLS-specific ones. `ibek-runtime-support` (GitHub) holds vendored runtime
patterns. A given module lives in exactly one of them, and which one is not
always obvious.

**Tier 2 — consumers.** `builder2ibek` pins the first two as submodules, and so
does each generic IOC repo — `ioc-dlslinuxvac` in this example. Generic IOC
repos additionally track `ioc-template` through copier.

**Tier 3 — instances.** The beamline services repos, `i15-services` here, which
hold the `ioc.yaml` you set out to write.

A fix in tier 1 has to be committed, merged, pinned, and released before tier 3
can use it. That climb is the cost.

## Why the sequence is forced

The steps below cannot be reordered, and several cannot be started until the
previous one has *landed* rather than merely been written.

1. **Convert.** `xml2yaml` produces `ioc.yaml`.

2. **Generate, and find out what is missing.** `ibek runtime generate2` is the
   only mechanism that reports gaps in entity models. In this case: an entity
   model absent entirely (`dlsPLC.NX102_femto`), three macros missing from
   another, a required parameter that almost no IOC supplies, a module with only
   one of its eight record types modelled (`ether_ip`), and a model demanding
   four inputs it should have derived (`mks937b.mks937bGaugeEGU`).

3. **Fix, in whichever repo owns the module.** Two of those modules were in the
   public repo and two in the DLS repo — identical work, split by ownership,
   through two different review processes on two different forges.

4. **Deal with whatever the fix invalidates.** A `vacuumSpace` defect surfaced
   here that was passing XMLbuilder short-names such as `GAUGE1` into database
   macros instead of device PV names, so every gauge, img and pirg link in every
   vacuum space group pointed at a PV that could never connect. It had also
   silently affected an IOC converted earlier the same day and reported clean,
   and it changed five committed CI samples.

5. **Bump the pins in `builder2ibek`,** then refresh the vendored copy of
   `ibek-support-dls` that CI uses (GitHub Actions cannot reach DLS GitLab), then
   regenerate the samples. The order is forced: the refresh tool refuses to run
   unless the pin is already committed, and the guard tests read
   `git ls-tree HEAD`, so staging is not enough. See
   [](../how-to/contribute.md) and the testing notes under
   `.claude/skills/shared/testing-and-ci.md`.

6. **Bump the same pins in the generic IOC repo and release it.** Only then can
   an instance's `values.yaml` point at an image containing the fix.

Steps 3, 5 and 6 each end at a push to a protected branch, which is where the
chain stops and waits for a person.

## The traps that do not announce themselves

Three classes of problem here fail silently, and they are the ones worth
designing against.

**Gaps that only exist until someone needs them.** There is no inventory of
which templates have entity models. In this example a sweep afterwards found
fifteen `dlsPLC` templates with no model at all — not broken, just absent,
waiting for whichever IOC needs one first. Every new IOC is therefore a
discovery exercise of unpredictable length.

**Changes that build green and fail in the cluster.** The generic IOC image was
two `ioc-template` versions behind, and the newer template carries the only two
things that make a vendored runtime pattern work: `ibek runtime place-files` in
`start.sh`, and the instance config folder on msi's include path. Without both,
the image builds cleanly and the IOC dies at container start. Nothing reported
the drift; it surfaced from a side question about a version pin. The same shape
applies to an `ibek` requirement below the floor `start.sh` needs. See
[](../how-to/runtime-support.md).

**Upstream changes not validated against converted IOCs.** A four-line addition
to the `positioner` entity model added a required parameter that nothing
consumes, no template accepts, and no builder XML can supply. It broke six
conversion samples immediately. Support-model repos are shared with hand-written
IOCs, whose authors can simply add the new parameter; converted IOCs cannot.

## What this suggests

The conversion is not the bottleneck and does not need attention. The chain
around it does, and the candidates in rough order of how much of the chain they
would shorten:

- **Make entity-model coverage knowable in advance.** A sweep comparing a
  module's `db/*.template` files against its entity models would turn every
  per-IOC discovery into a one-off per-module task. The data is already
  mechanically available.
- **Shorten the distance from a tier-1 fix to a usable image.** Three of the
  eleven steps exist only to propagate a pin.
- **Fail at build time, not boot time.** A check that the image's `ibek` and
  `start.sh` can actually serve the patterns an instance vendors would have
  caught the template drift immediately.
- **Reduce the number of copies of support metadata.** There are three: the
  public repo, the DLS repo, and a vendored copy so CI can run without DLS
  network access. A guard exists specifically to catch them drifting.
- **Validate support-model changes against the conversion samples,** so that a
  change which no converted IOC can satisfy is caught where it is made.

Two of the eleven steps stop for a human purely because `main` is protected on
the GitLab repositories. That is a permissions question rather than a design
one, but it is the only part of the chain that no amount of tooling can cross.

## Related

- [](../how-to/convert-ioc-instance.md) — the conversion workflow itself
- [](../how-to/runtime-support.md) — vendoring templates instead of building them
- [](../how-to/create-generic-ioc-repo.md) — the generic IOC and its submodule pins
- [](../tutorials/create-support-yaml.md) — authoring the entity models this page
  describes as frequently missing
