# Plan: `builder2ibek catio` — EtherCAT → fastcs-catio conversion

Status: **designed, not implemented**. Design settled 2026-08-07 in a grilling
session. Everything below was verified against real files — file:line citations
are load-bearing, but re-verify before asserting (repos move).

## Goal

DLS is replacing the custom EtherCAT scanner (`ethercat` support module) with
**fastcs-catio**, which auto-discovers the EtherCAT chain over ADS and generates
its own PV names. Those names differ from the legacy ones.

`builder2ibek catio <BLxxI-BUILDER-path> --services-repo <path>` must:

1. **Discover every EtherCAT chain** in the BUILDER tree — one per IOC XML
   containing an `ethercat.EthercatMaster` (the "scanner IOCs").
2. Model each chain and **predict** the PV names fastcs-catio will generate.
3. **Drop** the EtherCAT entities from the converted IOCs — a generated
   fastcs-catio IOC replaces them.
4. Find every IOC XML that references PVs produced by any chain and
   **substitute** the predicted names in.
5. Write the affected IOCs into a services repo as new IOC folders.
6. **Generate one fastcs-catio IOC per chain**, complete except for the ADS
   server IP address.

The scanner XMLs are **input-only** as far as their EtherCAT entities go:
consumed for the mapping, never emitted. Their non-EtherCAT entities are
converted as normal.

---

## Domain facts (verified)

### How fastcs-catio names things

`node_prefix`/`module_prefix`/`device_prefix` are `str.format` templates in
`CATioNameMappings` (`fastcs-catio/src/fastcs_catio/catio_controller.py:400-430`).
The DLS site config in `src/fastcs_catio/fastcs.yaml` is:

```yaml
name_mappings:
  device_prefix: "{id}:ETH{:02d}"
  node_prefix:   "BL04I-EA-E1RIO-{:02d}"
  module_prefix: "{node_prefix}:{group_alias}{:02d}"
```

* **node index** — `loc_in_chain.node`, incremented on every `EK1100` or box
  (`client.py:1420-1453`). 1-based ordinal of the coupler in chain order.
* **module index** — `loc_in_chain.position`, reset to 0 at each coupler then
  incremented, so the first terminal after a coupler is position 1. **But** when
  `module_prefix` contains `{group_alias}`, the positional index becomes a
  per-`(coupler, alias)` sequence number instead
  (`catio_controller.py:695-713`, `:772-802`).
* **group_alias** — from `terminal_types.yaml`, looked up by
  `(vendor_id, product_code, revision_number)` with **fallback to
  vendor+product** when the revision differs (`terminal_config.py:197-218`).
  This matters: the I21 XMLs declare `EL3104 rev 0x00120000`/`0x00130000` while
  the YAML holds `0x00100000`. Without the fallback the alias would silently
  degrade to `MOD`.
* **leaf** — `snake_to_pascal(fastcs_name)` (`fastcs/src/fastcs/util.py:14`,
  `fastcs/src/fastcs/transports/epics/util.py:18`). `fastcs_name` comes from the
  terminal YAML row, possibly shortened by `shorten_fastcs_name`
  (`catio_terminals/utils.py:301`) against a budget that **depends on the length
  of the PV prefix** (`fastcs_catio/utils.py:229-254`, 60-char EPICS limit).

Chain order in the XML is asserted to be true chain order, so all of this is
statically inferable — **no live ADS scan required**.

### Terminal map for I21 (verified both sides)

Legacy record names come from `/dls_sw/prod/R3.14.12.7/support/ethercat/7-5-3/db/*.template`.

| Terminal | `group_alias` | legacy leaf | fastcs-catio leaf |
|---|---|---|---|
| EL3104 | `10VAI` | `INPUT{n}:VALUE` | `AiStandardChannel{n}Value` |
| EL1014 | `24VDI` | `CHANNEL{n}:INPUT` | `Channel{n}` |
| EL2024-0010 | `12VDO` | `CHANNEL{n}:OUTPUT` | `Channel{n}` |
| EL3356-0010 | `AI` | `RMB:VALUE` | `RmbValueInt32Value` |

These four are the **only** leaves referenced anywhere in the I21 XMLs. No
consumer references `AL_STATE`, `ERROR_FLAG`, `SLIMIT*`, `SERROR`,
`SOVERRANGE`, `SSYNCERROR` or `STXPDO*`.

Worked example (`BL21I-VA-IOC-01`, `node_prefix: BL21I-VA-E1RIO-{:02d}`):

```
BL21I-VA-ERIO-01:MOD1:INPUT1:VALUE   -> BL21I-VA-E1RIO-05:10VAI01:AiStandardChannel1Value
BL21I-VA-ERIO-01:MOD5:CHANNEL1:INPUT -> BL21I-VA-E1RIO-05:24VDI01:Channel1
BL21I-VA-ERIO-04:MOD1:INPUT1:VALUE   -> BL21I-VA-E1RIO-01:10VAI01:AiStandardChannel1Value
```

Note `ERIO-01` becomes `E1RIO-**05**`. The legacy `ERIO-NN` numbers carry **no
ordering information** — VA-IOC-01's chain order is ERIO-04, -12, -03, -02, -01.

### Bugs found in the legacy I21 XMLs

These are real and must be fixed in the source XML before conversion (the tool
reports them and fails; it does not repair them).

1. **`DEVICE=` attributes disagree with chain position.** In ERIO-03 and
   ERIO-04 the `auto_EL1014` entities restart numbering at `MOD1` instead of
   continuing the coupler's position sequence:

   | Coupler | pos | type | chain-derived | declared `DEVICE=` |
   |---|---|---|---|---|
   | ERIO-03 | 3,4 | EL1014 | `MOD3,4` | `MOD1,2` ❌ |
   | ERIO-04 | 5,6 | EL1014 | `MOD5,6` | `MOD1,2` ❌ |

   This makes `ERIO-03:MOD1` ambiguous (an EL3104 *and* an EL1014 claim it).

2. **Three live references to undeclared names** — `ERIO-03:MOD3`,
   `ERIO-04:MOD5`, `ERIO-04:MOD6`, all from `rackFan_rio.rio_dinput`. These have
   been pointing at non-existent PVs for years. Under chain ordering they
   resolve correctly, i.e. the *consumers* were right and the `DEVICE=`
   attributes are wrong.

3. **`BL21I-VA-IOC-06`**: comment says `<!--Start of BL21I-VA-ERIO-05-->` but the
   `auto_EL3104` declares `DEVICE="BL21I-VA-ERIO-99:MOD1"`. Comments are
   unreliable.

4. **`BL21I-VA-IOC-05`**: a third coupler (`EK1100` + `EL2024`) has no comment
   and no `auto_*` entity — an unlabelled coupler that still consumes a node
   index.

### Consumer map for I21 (via builder2ibek's own `Builder`, comments excluded)

| IOC | refs to VA-IOC-01's chain | refs to other chains | attributes |
|---|---|---|---|
| `BL21I-VA-IOC-01` | 22 | — | `rackFan_rio.rio_dinput` |
| `BL21I-VA-IOC-02` | 29 | — | `mks937bGauge.plog_adc_pv`, `mks9xxGauge.plog_adc_pv` |
| `BL21I-VA-IOC-04` | 3 | 3 (ERIO-05/-06) | `mks937bGauge.plog_adc_pv` |
| `BL21I-VA-IOC-05` | 0 | 4 | `rackFan_rio.rio_dinput` |
| `BL21I-DI-IOC-01` | 0 | 96 | `records.ai.INP`, `femto200.*`, `DewarScales.*` |

`BL21I-VA-IOC-03` has **no** EtherCAT references (RGA only) — it is not a
dependent.

I21 has **four** independent chains: `VA-IOC-01`, `VA-IOC-05`, `VA-IOC-06`,
`DI-IOC-01`.

Two reference forms exist in attribute values:

```
rio_dinput="BL21I-VA-ERIO-01:MOD5:CHANNEL1:INPUT"    # bare PV
INP="BL21I-DI-ERIO-10:MOD1:INPUT1:VALUE CP"          # PV + CA link flag
```

---

## Decisions

**D1 — Chain order in the XML is authoritative.** Node index = 1-based coupler
ordinal; position = 1-based offset after its coupler. No live ADS scan.

**D2 — Legacy canonical names are derived from chain ordering, not from
`DEVICE=`.** The declared `DEVICE=` is used only to derive each coupler's label
(from the *prefix* of its terminals' `DEVICE=` values, which must be unanimous)
and as a cross-check. `<!--Start of ...-->` comments are ignored entirely —
they are unvalidatable free text, they are wrong in VA-IOC-06, and
`Builder._parse` (`src/builder2ibek/builder.py:44-56`) already discards comment
nodes.

**D3 — Substitution is keyed on the full legacy PV** (prefix *and* leaf), applied
token-wise within attribute values, bounded by start/whitespace/end, preserving
anything that follows (`CP`, `CPP`, `MS`, …). Prefix-only substitution is unsafe
because `DEVICE=` names are ambiguous (bug 1); the leaf is what disambiguates the
terminal, and it doubles as a type check.

**D4 — Fail loudly, never guess.** Hard-fail with per-entity pointers when:
1. a referenced `MODn` exceeds the coupler's terminal count;
2. the leaf does not exist on the terminal type at that position;
3. two couplers in one chain resolve to the same label;
4. a coupler's `auto_*` entities disagree about its label;
5. an IOC references a label that **no chain in the BUILDER tree** declares —
   under D7 every chain is discovered, so this is a genuine error (typo, or a
   cross-beamline reference), not a scoping artefact;
6. a terminal type is absent from `terminal_types.yaml` — its `group_alias`
   would silently degrade to `MOD` and its leaf map is unknown.

The report must name the IOC, the entity, and the attribute — e.g.
`BL21I-VA-IOC-01, entity VAFAN4, arg rio_dinput`. Rationale: chain ordering
would silently "repair" bug 2 as a side effect of a name migration. That repair
should be a reviewed XML fix, not a conversion artefact.

**D5 — Do not reimplement the naming rule.** Add a public, hardware-free naming
API to fastcs-catio and depend on it. The needed pieces are currently private
(`_resolve_controller_name_and_path`, `_module_alias_indices`) and entangled with
live ADS discovery. Proposed shape:

```python
def predict_names(
    chain: list[tuple[str, int]],          # [(type_name, revision), ...] in chain order
    mappings: CATioNameMappings,
    root_id: str,
) -> dict[tuple[int, int], str]:           # (node, position) -> PV prefix
```

It must accept terminal **type names** (`"EL3104"`), because that is all the
builder XML has — `type_rev="EL3104 rev 0x00120000"` — whereas the runtime
lookup keys on `(vendor_id, product_code)`. Lock it with a test in fastcs-catio
so drift breaks the repo that caused it.

**D6 — Substitute on parsed entity values, as a finalizer.** Not on XML text.
`make_entity` (`convert.py:174-208`) leaves PV strings as strings, so there is
nothing to corrupt, and entity-level access gives the provenance D4 needs.

**D7 — Auto-discover every chain in the beamline; one invocation does the lot.**
The input is the BUILDER root (e.g. `.../BL21I-BUILDER/5-19`); the tool globs
`etc/makeIocs/*.xml`, treats every XML containing an `ethercat.EthercatMaster`
as a scanner, and builds one merged substitution map across all chains. This is
what makes `BL21I-VA-IOC-04` — which straddles two chains — convertible at all:
it is written once, complete. D4.5 therefore fires only for a reference to a
label no chain in the tree declares, which is a genuine error.

*(Supersedes the earlier one-chain-per-invocation design with `--also-chain`.)*

**D8 — Output is a services repo, not a single YAML.** `--services-repo <path>`
replaces `xml2yaml`'s `--yaml`. Scaffold each affected IOC from `.ioc_template`.
Per CLAUDE.md, an existing folder with `dev-c7:` in its `values.yaml` is legacy —
delete the whole folder and recreate.

**D10 — Generate the fastcs-catio IOC for each chain.** One services-repo folder
per chain, named after its scanner IOC with `IOC` → `CATIO`, so provenance is
obvious and adding a chain never renumbers an existing one:

| Scanner IOC | fastcs-catio IOC | services folder |
|---|---|---|
| `BL21I-VA-IOC-01` | `BL21I-VA-CATIO-01` | `bl21i-va-catio-01` |
| `BL21I-VA-IOC-05` | `BL21I-VA-CATIO-05` | `bl21i-va-catio-05` |
| `BL21I-VA-IOC-06` | `BL21I-VA-CATIO-06` | `bl21i-va-catio-06` |
| `BL21I-DI-IOC-01` | `BL21I-DI-CATIO-01` | `bl21i-di-catio-01` |

Two files, matching the deployed-fastcs-IOC shape in
`/workspaces/b01-1-services/services/bl01c-ea-align-01/`:

`config/fastcs.yaml` — modelled on fastcs-catio's own
`src/fastcs_catio/fastcs.yaml`, **not** on the older
`transport: - ioc: pv_prefix:` form some services repos still use:

```yaml
controllers:
  - id: BL21I-VA-CATIO-01
    type: fastcs_catio.CATioServerController
    tcp_settings:
      target_ip: "REPLACE_WITH_ADS_SERVER_IP"   # only unknown value
      target_port: 27905
    route:
      route_name: ""
      user_name: "Administrator"
      password: "1"
    scan_timings:
      poll_period: 1.0
      notification_period: 0.2
    name_mappings:
      device_prefix: "{id}:ETH{:02d}"
      node_prefix: "BL21I-VA-E1RIO-{:02d}"       # E{n}RIO per chain, see D11
      module_prefix: "{node_prefix}:{group_alias}{:02d}"
transport:
  - epicsca: {}
    gui:
      output_dir: ./screens
      title: "BL21I VA EtherCAT chain (from BL21I-VA-IOC-01)"
```

`values.yaml`:

```yaml
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: ghcr.io/diamondlightsource/fastcs-catio:REPLACE_WITH_PINNED_TAG
  args:
    - stdio-expose --ptty --stdin --ctrl-d 'fastcs-catio run /epics/ioc/config/fastcs.yaml'
```

`fastcs-catio run <yaml>` is the yaml-driven entry point from FastCS `_launch`
(`fastcs_catio/__main__.py:38`); the bespoke `fastcs-catio ioc <pv_prefix>
<tcp_server>` command bypasses the config file and must not be used here.

The `name_mappings` written here and the templates builder2ibek used to predict
names are **the same values by construction** — the tool must emit both from one
source, since a divergence points every rewritten PV at nothing.

**D11 — Chains are distinguished by the `E{n}RIO` ordinal, not by a node
offset.** `loc_in_chain.node` restarts at 1 for every chain
(`client.py:1433-1444`), so on I21 three separate VA chains would each claim
`BL21I-VA-E1RIO-01`. Resolve it by giving each chain in a domain its own
`node_prefix` literal, incrementing the digit after `E`:

| Scanner IOC | Domain | Chain ordinal | Couplers | `node_prefix` | Allocated |
|---|---|---|---|---|---|
| `BL21I-VA-IOC-01` | `BL21I-VA` | 1 | 5 | `BL21I-VA-E1RIO-{:02d}` | `E1RIO-01..05` |
| `BL21I-VA-IOC-05` | `BL21I-VA` | 2 | 3 | `BL21I-VA-E2RIO-{:02d}` | `E2RIO-01..03` |
| `BL21I-VA-IOC-06` | `BL21I-VA` | 3 | 1 | `BL21I-VA-E3RIO-{:02d}` | `E3RIO-01` |
| `BL21I-DI-IOC-01` | `BL21I-DI` | 1 | 10 | `BL21I-DI-E1RIO-{:02d}` | `E1RIO-01..10` |

This needs **no change to fastcs-catio** — `node_prefix` is already a per-IOC
literal, and each generated `fastcs.yaml` simply carries a different one. It is
also the intended reading of the name: the library default is
`{device_prefix}:E1RIO{:02d}` (`catio_controller.py:429`), where the `1` is the
EtherCAT device ordinal. Chain *n* → `E{n}RIO` matches that semantics rather
than fighting it.

Chain ordinals are allocated per `(beamline, domain)` — `BL21I-VA` and
`BL21I-DI` number independently — in ascending scanner-IOC-name order.
**Ordinals must be sticky**: on re-run the tool reads back the `node_prefix` of
any already-generated `config/fastcs.yaml` and keeps it, allocating only for
chains it has not seen. Otherwise inserting a chain (say a future
`BL21I-VA-IOC-03`) would renumber every downstream PV.

This restores the property the legacy naming had — `ERIO-NN` was unique across
the whole `BL21I-VA-` domain — without preserving the actual numbers.

*(Supersedes an earlier proposal to add `node_index_offset` to
`CATioNameMappings`. No longer needed; do not implement it.)*

**D9 — `/beamline-convert` must learn about this.** EtherCAT IOCs must be
excluded from the per-IOC `xml2yaml` fan-out and handled by one `catio` call per
chain instead.

---

## Implementation steps

1. **fastcs-catio PR** — extract the naming rule into `predict_names()` (D5),
   hardware-free, keyed on type names, with a locking test. This is the *only*
   fastcs-catio change required. Blocks step 4 but can proceed in parallel
   behind a thin shim.

2. **`src/builder2ibek/catio.py`** — pure chain modelling:
   * glob `etc/makeIocs/*.xml`, identify scanners by `EthercatMaster` (D7);
   * parse each scanner XML into an ordered slave list;
   * assign `(node, position)` per D1;
   * allocate sticky per-domain `E{n}RIO` chain ordinals per D11;
   * derive coupler labels per D2;
   * build the canonical legacy PV set (prefix × leaves valid for that terminal
     type);
   * return `dict[legacy_pv, new_pv]` plus a list of diagnostics.

   No I/O, no services repo, no fastcs runtime → unit-testable directly against
   `tests/samples/BL21I-VA-IOC-01.xml`.

3. **Leaf translation table** — legacy `.template` leaf → fastcs `fastcs_name`,
   per terminal type. Start with the four I21 types; **fail on unknown types**
   rather than passing them through.

4. **Wire in `predict_names()`** from step 1.

5. **Extend `src/builder2ibek/converters/ethercat.py`.** It already drops all
   EtherCAT entities and replaces `EthercatMaster` with a TODO
   `epics.PostStartupCommand`. Add a `finalize(ioc)` (picked up automatically by
   `moduleinfos.py:22-24`) that applies the substitution map carried on
   `Generic_IOC`.
   * **Bug to fix while there**: the module-level `_dummy_inserted` global is set
     but never read or reset — it will leak across IOCs in a multi-IOC process.

6. **CLI** — `builder2ibek catio` in `src/builder2ibek/__main__.py`:

   ```
   builder2ibek catio BUILDER_PATH
       --services-repo PATH
       [--node-prefix TEXT] [--module-prefix TEXT] [--device-prefix TEXT]
       [--dry-run]
   ```

   `BUILDER_PATH` is the BUILDER root (`.../BL21I-BUILDER/5-19`); the tool globs
   `etc/makeIocs/*.xml` itself — same convention as the existing
   `beamline2yaml` stub. The name-mapping templates default to the DLS
   convention derived from each scanner IOC's domain
   (`BL21I-VA-IOC-01` → `BL21I-VA-E1RIO-{:02d}`) and are written verbatim into
   the generated `fastcs.yaml`, so prediction and deployment cannot diverge
   (D10).

7. **Services repo output** (D8) — scaffold from `.ioc_template`, honour the
   `dev-c7:` legacy rule.

8. **fastcs-catio IOC generation** (D10) — emit `config/fastcs.yaml` +
   `values.yaml` per chain, with `target_ip` and the image tag left as explicit
   `REPLACE_WITH_*` placeholders. The final report must list every placeholder
   so none ships unfilled.

9. **`/beamline-convert` update** (D9).

10. **Tests** — add `BL21I-VA-IOC-01/-02/-04` to `tests/samples/`; assert the
    generated map against a checked-in expected table; assert `E{n}RIO` ordinal
    allocation and its stickiness across re-runs; assert each D4 failure mode
    fires. Run as CI does: `env -u EPICS_ROOT uv run pytest`.

## Open items

* fastcs-catio inconsistency worth reporting upstream: attribute creation filters
  on `selected` alone (`catio_dynamic_controller.py:61`) while symbol expansion
  additionally drops rows where `bit_offset % 8 != 0` (`symbols.py:164`). So
  EL3104's `AiStdCh1StsLim1`/`StsLim2` PVs are created but can never update.
  Harmless here (nothing references them) but it means "PV exists" ≠ "PV works" —
  do not use the naming API as an existence oracle.
* Chain-ordinal stickiness has an unhandled edge: if a chain is *removed* from
  the BUILDER tree its `E{n}RIO` ordinal stays reserved (correct — reusing it
  would renumber live PVs), but nothing reclaims it. Acceptable; note it in the
  report.
* `E{n}RIO` assumes fewer than 10 chains per domain, beyond which `E10RIO`
  widens the segment. No beamline is near this.
* Only I21 has been examined. Other beamlines may use terminal types absent from
  `terminal_types.yaml` (37 types present), which would degrade `group_alias` to
  `MOD`.
