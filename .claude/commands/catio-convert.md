---
argument-hint: <path/to/BLxxI-BUILDER> [<path/to/services-repo>]
description: Convert every EtherCAT chain in a beamline from the legacy ethercat scanner to fastcs-catio, rewriting all consumer PV references and generating the fastcs-catio IOCs.
---

# CATio Convert Workflow

Convert every EtherCAT chain declared in the BUILDER tree `$1`, every IOC that
references those chains, and generate the replacement fastcs-catio IOCs — all
into the services repo `$2`.

> **Predicting PV names needs `fastcs_catio` importable.** Everything else —
> chain modelling, diagnostics, the report — works without it. If the run stops
> with an ImportError, use an interpreter that has both projects installed.
> [.claude/plans/catio-conversion.md](../plans/catio-conversion.md) carries the
> design, the verified domain facts, and the decisions (D1–D11) behind them.
> Do not re-derive the naming rule — it lives in `fastcs_catio.naming`.

---

## What makes this different from `/beamline-convert`

`/beamline-convert` converts each XML in isolation. This one is **cross-IOC and
whole-beamline**:

* The scanner IOCs are the only place the EtherCAT chains are declared, but
  their PVs are consumed by *other* IOCs.
* The EtherCAT entities are **dropped**; generated fastcs-catio IOCs replace
  them.
* fastcs-catio auto-discovers each chain and generates **different** PV names,
  so every reference in every dependent IOC must be rewritten.
* All chains are handled in **one** invocation, because an IOC may consume more
  than one chain (`BL21I-VA-IOC-04` does) and must be written once, complete.

Legacy `ERIO-NN` labels carry **no ordering information**. fastcs-catio numbers
couplers by chain order, so `BL21I-VA-ERIO-01` may well become
`BL21I-VA-E1RIO-05`. Never assume the number is preserved.

## Step 1 — Resolve services repo

Follow [services-repo-resolution.md](../skills/shared/services-repo-resolution.md)
using `$2` if provided, otherwise the beamline prefix implied by `$1`.

## Step 2 — Dry run and read the report

```bash
uv run builder2ibek catio $1 --services-repo <repo> --dry-run
```

Report to the user, before writing anything:

* every chain discovered, with its scanner IOC, coupler order, derived labels,
  terminal types and positions;
* the `E{n}RIO` chain ordinal allocated to each chain, and whether it was newly
  allocated or carried over from an existing `config/fastcs.yaml`;
* the predicted fastcs-catio prefix for every module;
* every IOC that will be modified and how many substitutions each receives;
* the fastcs-catio IOCs that will be generated;
* **every diagnostic**.

## Step 3 — Resolve diagnostics before writing

The tool hard-fails rather than guessing (decision D4). Expect these, and treat
each as a question for the user — **do not work around them**:

| Diagnostic | Meaning | Action |
|---|---|---|
| `MODn` out of range | reference beyond the coupler's terminal count | fix the source XML |
| leaf invalid for terminal type | e.g. `CHANNEL1:INPUT` on an EL3104 | fix the source XML |
| duplicate coupler label | two couplers derive the same `ERIO-NN` | fix the source XML |
| coupler label not unanimous | a coupler's `auto_*` entities disagree | fix the source XML |
| label matches no chain | reference to a chain not in this BUILDER tree | investigate — likely a typo or a cross-beamline reference |
| unknown terminal type | not in `terminal_types.yaml` | add it upstream; do not pass through |

The I21 XMLs contain **known real bugs** of the first and second kinds — the
`auto_EL1014` entities in `ERIO-03`/`ERIO-04` restart numbering at `MOD1`
instead of continuing the coupler's position sequence, and three live
`rackFan_rio` references point at names nothing declares. These are genuine
long-standing defects in the source XML. They get fixed upstream, not papered
over here. See the plan's "Bugs found" section.

## Step 4 — Convert

Re-run without `--dry-run` once the report is clean. Then for each affected
*legacy* IOC folder, follow the normal `/ioc-convert` phases for support YAML
creation and `ibek generate2` validation — `catio` produces `ioc.yaml`, it does
not validate the support modules those IOCs need.

The generated fastcs-catio IOCs need none of that: they are FastCS IOCs, not
ibek IOCs, and carry no `ioc.yaml`.

## Step 5 — Verify the substitutions landed

```bash
grep -rn "ERIO" <services-repo>/services/*/config/ioc.yaml
```

Any surviving legacy `ERIO-NN:MODn` reference in an IOC that `catio` claimed to
convert is a bug — report it rather than hand-editing.

## Step 6 — Fill in the placeholders

Each generated fastcs-catio IOC has exactly two values `catio` cannot know:

```bash
grep -rn "REPLACE_WITH_" <services-repo>/services/*catio*/
```

* `target_ip` — the ADS/TwinCAT server for that chain. Ask the user; it is *per
  chain*, not per beamline.
* the container image tag — pin it, do not leave `latest`.

Do not invent either. List them in the final report if unresolved.

## Step 7 — Report

List: chains discovered, `E{n}RIO` ordinal allocation, IOCs converted with
substitution counts, fastcs-catio IOCs generated, placeholders still unfilled,
diagnostics resolved, and source XML fixes still outstanding.

Suggest git commands; do not commit.
