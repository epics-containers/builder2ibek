# catio sample fixtures

Inputs and checked-in expected results for `builder2ibek catio` — the migration
of DLS beamlines off the legacy `ethercat` support module onto `fastcs-catio`.

These live in a **subfolder** on purpose. `tests/samples/make_samples.sh` runs
`ls *.xml` from `tests/samples/`, and `tests/test_file_conversion.py` uses
`SAMPLES.glob("*.xml")` — both non-recursive. Keeping these XMLs in `catio/`
keeps them out of the `xml2yaml` + `generate2` regeneration set and out of the
`GENERATED_AGAINST` pin-freshness contract. **Do not move them up a level.**

## Provenance of the XMLs

| | |
|---|---|
| Source | `/dls_sw/work/R3.14.12.7/support/BL21I-BUILDER/etc/makeIocs/` |
| BUILDER revision | `cf39c887ac8a34d01e637ebbc71a58a55f6a9a29` (2026-05-28, "EA-03,MO-18,VA-02: update support dependencies") |
| Copied | 2026-08-07 |
| Modified? | **No.** Byte-for-byte copies, verified with `cmp` against the source. Do not reformat, re-indent or run a formatter over them. |

| file | md5 | role |
|---|---|---|
| `BL21I-VA-IOC-01.xml` | `974ddef488927ae1d6bb2d3734eabc68` | scanner (5 couplers) |
| `BL21I-VA-IOC-05.xml` | `5900c70024c02459b14fb6df5c7f3b26` | scanner (3 couplers, one unlabelled) |
| `BL21I-VA-IOC-06.xml` | `1920063f50757c5f68232e775d72c349` | scanner (1 coupler; declares `ERIO-99`, contradicting its comment) |
| `BL21I-DI-IOC-01.xml` | `25a4799e6442107f05438545e08b522e` | scanner (10 couplers; the hard one) |
| `BL21I-VA-IOC-02.xml` | `e99d40a496f4ad4fd9b11172f2a2a444` | consumer only |
| `BL21I-VA-IOC-04.xml` | `35bb4fcead376aa40037002bedfc4a7b` | consumer only; straddles a clean and a failing chain |

`BL21I-VA-IOC-03.xml` is deliberately absent: it has no EtherCAT references.
Together these six carry **every** one of the 247 EtherCAT reference rows in the
beamline (155 / 44 / 29 / 12 / 6 / 1 for DI-01, VA-01, VA-02, VA-05, VA-04,
VA-06).

## `expected_chains.json`

The chain topology the tool must reproduce from the four scanner XMLs:

```json
{"<scanner ioc>": {"couplers": [
  {"node": 0, "label": "BL21I-VA-ERIO-04", "slave_name": "DCS00025070",
   "terminals": [
     {"position": 0, "type_name": "EK1100", "revision": "0x00120000",
      "declared_device": "", "entity_type": null, "entity_name": null,
      "slave_name": "DCS00025070"},
     ...]}]}}
```

Conventions, which match `.catio-spec/spec_ground.json` exactly:

* `node` is **0-based** and increments per coupler in bus order.
* `position` **0 is the coupler itself**; the first terminal after it is 1.
  Every coupler therefore has a `terminals[0]` whose `type_name` is `EK1100`.
* `revision` is the verbatim hex string from the XML's `type_rev`
  (`"EL3104 rev 0x00120000"` → `type_name` `EL3104`, `revision` `0x00120000`),
  not an int.
* `declared_device` is `""` (not `null`) when no `auto_*` entity binds that
  terminal — verbatim from the ground truth.
* `label` is `null` when underivable (the ground truth spells this `""`).

### How it was derived

`node`, `position`, `type_name`, `revision` and `declared_device` come straight
from `.catio-spec/spec_ground.json`'s `scanners[].couplers[].terminals[]`, and
`label` from its `derived_label`. The three fields the ground truth does not
carry — `entity_type`, `entity_name`, `slave_name` — were derived by re-parsing
each XML with `builder2ibek.builder.Builder` and matching each `auto_*`
entity's `PORT=` to an `EthercatSlave`'s `name=`.

The whole file was then re-derived from the XMLs alone and compared field by
field with the ground truth, using these rules:

* **D1 chain topology** — walk `ethercat.EthercatSlave` elements in XML order.
  A slave is a coupler if `type_name == "EK1100"` or it matches
  `^(E[PQR]P?\d{4})`; then `node += 1` and `position = 0`. Otherwise
  `position += 1`. `EK1122` junctions are *not* couplers (`EK` is not
  `E[PQR]`) and consume an ordinary position — see `BL21I-DI-IOC-01` node 8.
* **D2 label derivation** — the unanimous part before `:MOD` of the
  `DEVICE=` values of the `auto_*` entities bound to that coupler's terminals.
  `DEVICE=` values with no `:MOD` part (`BL21I-OP-LED-01`,
  `BL21I-MO-PIEZO-01`, …) are ignored. `<!--Start of ...-->` comments are
  ignored entirely — they are unvalidatable free text and are wrong in
  `BL21I-VA-IOC-06`.

**Result: zero discrepancies.** The XMLs and `spec_ground.json` agree on the
flat bus order, every `type_rev`, every coupler/position assignment, every
`slave_name` and every derived label.

## `expected_references.json`

The 247 `references[]` rows from `.catio-spec/spec_ground.json`, verbatim and in
order, so tests can assert that every one either rewrites to a new PV or
produces a named diagnostic.

```json
[{"ioc": "BL21I-DI-IOC-01", "entity_type": "BL21I.DewarScales",
  "entity_name": "SMPL.SCALES", "attribute": "LOAD_CELL_1",
  "value": "BL21I-DI-ERIO-04:MOD12:RMB:VALUE"}, ...]
```

Notes for anyone writing assertions against it:

* `value` is the **whole attribute value**, including any trailing link flags
  (`"BL21I-DI-ERIO-10:MOD1:INPUT1:VALUE CP"`). That is what the link-direction
  rule keys on, and what token-wise substitution must preserve.
* `entity_name` is the entity's `name=` attribute **except for `records.*`
  entities, which carry their PV in `record=` instead**. Index by
  `attributes.get("name") or attributes.get("record")` when looking a row up.
* `entity_type` is `"<module>.<element>"`, e.g. `ethercat.auto_EL3104`.
  Distribution: `femto.femto200` 88, `mks937b.mks937bGauge` 30,
  `ethercat.auto_EL2024_0010` 29, `rackFan.rackFan_rio` 26,
  `ethercat.auto_EL3104` 25, `records.ai` 24, `ethercat.auto_EL1014` 12,
  `mks9xx.mks9xxGauge` 5, `BL21I.DewarScales` 4, `ethercat.auto_EL3356_0010` 4.

### How it was validated

Every row was checked twice against its copied XML: that `value` occurs as a
substring of the file, and that the entity identified by
`(entity_type, entity_name)` really carries that exact string on that
`attribute`. **All 247 rows passed.**

## Interesting cases these fixtures pin down

* `BL21I-VA-IOC-01` node 0 (`BL21I-VA-ERIO-04`) — four `auto_EL3104` declaring
  `MOD1`..`MOD4` at positions 1–4, then two `auto_EL1014` **restarting at
  `MOD1`** at positions 5–6. The dual-key substitution map is what makes this
  harmless. Node 2 (`ERIO-03`) has the same defect.
* `BL21I-VA-IOC-05` node 2 — an unlabelled coupler carrying a plain `EL2024`
  (not `-0010`) with no `auto_*` entity at all.
* `BL21I-VA-IOC-06` — a single coupler whose `auto_EL3104` declares
  `BL21I-VA-ERIO-99`, while the `<!--Start of BL21I-VA-ERIO-05-->` comment
  above it says otherwise. The declaration wins.
* `BL21I-DI-IOC-01` nodes 7 and 8 — **two physical couplers deriving the same
  label** `BL21I-DI-ERIO-01`, with continuous MOD numbering (MOD6–MOD15 then
  MOD16–MOD20). Declared names stay distinct; only the chain-derived aliases
  collide.
* `BL21I-DI-IOC-01` node 1 (`BL21I-DI-ERIO-05`) — non-numeric MOD names
  `MODSAM3`..`MODSAM7`, referenced live by `femto200`.
* `BL21I-DI-IOC-01` — five `EL2024` slaves bound to `auto_EL2024_0010`
  entities (a genuine type mismatch, e.g. slave `DCS00024653`), and terminal
  types well outside the five inventoried in `leaves.py`: `EL3602`, `EL2595`,
  `EL9512`, `EL9510`, `EL9505`, `EL2124`, `EL4134`, `EL3124`, `EK1122`.
* **Four** of `BL21I-DI-IOC-01`'s ten couplers have `label: null` — nodes 0, 4,
  5 and 6. (`.catio-spec/HANDOFF.md` says "5 of 10 couplers have no derivable
  label"; the ground truth data and the XML both say four. Trust the data.)
  Nodes 0, 4 and 5 have no `auto_*` entity at all; node 6 has two, but both
  declare a `DEVICE=` with no `:MOD` part — `BL21I-MO-PIEZO-01`
  (`auto_EL4134`) and `BL21I-DI-LED-01` (`auto_EL2595`) — so both are ignored
  for label derivation (`device-without-mod`, WARNING) and nothing is left to
  derive from. It is the only coupler that reaches `unlabelled-coupler` *via*
  `device-without-mod`.
