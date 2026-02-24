# dlsPLC migration reference

This page documents which older DLS vacuum/interlock support modules are
obsolete and how their builder XML entities map to `dlsPLC` equivalents in
`ioc.yaml`.

`builder2ibek xml2yaml` performs most of these translations **automatically**.
The sections below note where automatic conversion is implemented, where it is
incomplete, and the argument transformations applied.

**Origin**: the authoritative migration guide is the DLS Confluence page
*"Upgrade a Vacuum IOC to use dlsPLC"* (internal access required).  This page
captures the same rules in a form usable without Confluence access.

---

## Why these modules are obsolete

The older modules (`vacuumValve`, `vacuumPump`, `interlock`, `temperature`,
`flow`) each shipped separate EPICS templates for the two PLC communication
protocols — FINS and Hostlink — doubling maintenance burden.  `dlsPLC` provides
a single protocol-independent layer 3, so only one device template per device
type is needed.

---

## Build requirements for dlsPLC IOCs

Add to `configure/RELEASE`:
```
calc   = ...
busy   = ...
```

Add to the DBD file:
```
calcSupport.dbd
busyRecord.dbd
```

If migrating from **Hostlink** to FINS, in the startup script replace:
```
HostlinkInterposeInit("ty_40_0")
```
with:
```
finsDEVInit("VLVCC1", "ty_40_0")
```
and update all references to `ty_40_0` → `VLVCC1`.

---

## Module replacement table

### vacuumValve module

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `vacuumValve.vacuumValveRead` | `dlsPLC.read100` | **Yes** | `century=0` |
| `vacuumValve.vacuumValveRead2` | `dlsPLC.read100` | **No** — raises error | `century` = block number (e.g. `2` reads DM200–299); see below |
| `vacuumValve.vacuumValve` | `dlsPLC.vacValve` | **Yes** | `valve×10 → addr`; `crate → vlvcc` (full crate name) |
| `vacuumValve.vacuumValve_callback` | `dlsPLC.vacValve` | **Yes** | Same as above |
| `vacuumValve.vacuumValveBistable` | `dlsPLC.vacValveBistable` | No | `valve×10 → addr` |
| `vacuumValve.vacuumValveGroup` | `dlsPLC.vacValveGroup` | **Yes** | Arguments identical |
| `vacuumValve.vacuumValveReadOnly` | `dlsPLC.vacValveReadOnly` | No | Direct replacement |
| `vacuumValve.vacuumValveReadExtra` | *(no direct replacement)* | No | Use multiple `dlsPLC.read100` instances |
| `vacuumValve.externalValve` | `dlsPLC.externalValve` | No | Direct replacement |

For valves that used `tclose` macros, use `dlsPLC_vacValveTclose.template`
(entity type `dlsPLC.vacValveTclose`).

For endstation PLCs with more than 6 valves, use `dlsPLC.vacValveDebounce`
instead of `dlsPLC.vacValve`.

### vacuumPump module

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `vacuumPump.vacuumScrollPump` / `_asyn` | `dlsPLC.vacPump` | No | `valve×10 → addr` |
| `vacuumPump.vacuumTurboPump` / `_asyn` | `dlsPLC.vacPump` | No | `valve×10 → addr` |
| `vacuumPump.vacuumRootsPump` | `dlsPLC.vacPump` | No | `valve×10 → addr` |

### interlock module

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `interlock.interlock` | `dlsPLC.interlock` | **Yes** | See address and field-name changes below |
| `interlock.overrideRequestMain` | `dlsPLC.overrideRequestMain` | **Yes** | `addr`+`in`+`out` → `outaddr`; see below |
| `interlock.overrideRequestIndividual` | `dlsPLC.overrideRequestIndividual` | **Yes** | `FIELD` argument removed |

### temperature module

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `temperature.temperaturePLCRead` / `_asyn` | 2× `dlsPLC.read100` | **Partial WIP** | `century=1` (setpoints), `century=2` (readbacks) |
| `temperature.temperaturePLC` / `_asyn` | `dlsPLC.temperature` | No | `addr`+`indx` → 2-digit `offset`; see below |

### flow module

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `flow.flow` | *(no replacement)* | No | Still works; `LOLO` PV points at `dlsPLC.interlock` output |
| `flow.flow_asyn` | `dlsPLC.flow` | No | Address recalculation required; see below |

### Other templates

| Old XML type | dlsPLC replacement | Auto-converted? | Notes |
|---|---|---|---|
| `vacuumValve.reboot_rga` | `dlsPLC.reboot_rga` | No | `DM → addr` |
| `vacuumValve.fvg_asyn` | *(remove)* | No | Point GUI directly at gauge interlock bit |
| `vacuumValve.overrideRequestMain` | `dlsPLC.overrideRequestMain` | **Yes** | Via interlock converter |

---

## Argument transformation rules

### `valve → addr`

All valve and pump templates used a `valve` number (1-based, sometimes
zero-padded).  dlsPLC uses `addr` = `valve × 10`.

```
valve=1  → addr=10
valve=2  → addr=20
valve=12 → addr=120
```

### `vlvcc` — full crate name

The `vlvcc` argument in dlsPLC templates must be the **full** PV device name of
the valve crate controller, not a short alias:

```
# Old
vlvcc="VLVCC01"

# New
vlvcc="BL04I-VA-VLVCC-01"
```

### `interlock` — field names and addresses

Interlock bit labels `ilkA`–`ilkF` become `ilk10`–`ilk16` (decimal):

```
ilkA → ilk10
ilkB → ilk11
ilkC → ilk12
ilkD → ilk13
ilkE → ilk14
ilkF → ilk15
```

The `addr` argument is used **directly** (not multiplied by 10). However, if
your original interlock used a reduced address because `vacuumValveRead2` was
subtracting an offset, **add that offset back**:

```
# Old: addr=07 with vacuumValveRead2 READFROM2=800 → effective DM=807
# New: addr=807
```

### `overrideRequestMain` — `outaddr`

The three arguments `addr`, `in`, `out` collapse into a single `outaddr`:

```
outaddr = (addr × 10) + out
```

The input address is always `outaddr - 1`.

Example: `addr=08, in=1, out=0` → reads DM81, writes DM80 → `outaddr=80`.

The `in`, `out`, and `addr` arguments are removed; `name` is also removed.

### `temperaturePLC` — `offset`

The `addr` and `indx` arguments are combined into a 2-digit `offset`:

```
offset = (addr × 10) + indx
```

Example: `addr=3, indx=4` → reads from DM234, writes to DM134 → `offset=34`.

### `flow_asyn` — address recalculation

If your `flow_asyn.template` had non-zero `loarea`/`loloarea`, look up the
`READFROM2` value in the corresponding `vacuumValveRead2_asyn.template` and add
it to `loaddress`/`loloaddress`:

```
# Old: loloarea=2, loloaddress=12, READFROM2=800
# New: loloaddress=812  (loloarea removed)
```

---

## ioc.yaml examples

### vacuumValveRead → dlsPLC.read100

**Old XML:**
```xml
<vacuumValve.vacuumValveRead device="BL04I-VA-VLVCC-01" name="VLVCC01" port="ty_40_0"/>
```

**New ioc.yaml:**
```yaml
- type: dlsPLC.read100
  century: 0
  device: BL04I-VA-VLVCC-01
  port: ty_40_0
```

Note: `name` is removed (it was only used to cross-reference other components
in builder XML; ibek uses the `device` PV name instead).

### vacuumValve → dlsPLC.vacValve

**Old XML:**
```xml
<vacuumValve.vacuumValve_callback
    crate="VLVCC01"
    device="BL04I-VA-VALVE-01"
    valve="01"
    ilk0="Air Healthy" ilk1="IMG 03 Healthy" ilk2="IMG 04 Healthy"
    ilk3="PIRG 03 Healthy" ilk4="PIRG 04 Healthy" ilk5="QBPM1 Out/V1 Open"
    ilk6="Unused" ilk7="QBPM3 Out/V1 Open" ilk8="Unused" ilk9="Unused"
    ilkA="Unused" ilkB="Unused" ilkC="Unused" ilkD="Unused" ilkE="Unused"
    ilkF="Valve OK"
    gilk0="GAUGE-01" gilk1="GAUGE-02" gilk2="GAUGE-03"
    gilk3="GAUGE-04" gilk4="GAUGE-05" gilk5="GAUGE-06"
    name="VALVE1"/>
```

**New ioc.yaml** (blank `ilk` fields are dropped automatically):
```yaml
- type: dlsPLC.vacValve
  addr: 10
  device: BL04I-VA-VALVE-01
  vlvcc: BL04I-VA-VLVCC-01
  port: ty_40_0
  ilk0: Air Healthy
  ilk1: IMG 03 Healthy
  ilk2: IMG 04 Healthy
  ilk3: PIRG 03 Healthy
  ilk4: PIRG 04 Healthy
  ilk5: QBPM1 Out/V1 Open
  ilk7: QBPM3 Out/V1 Open
  ilk15: Valve OK
  gilk0: GAUGE-01
  gilk1: GAUGE-02
  gilk2: GAUGE-03
  gilk3: GAUGE-04
  gilk4: GAUGE-05
  gilk5: GAUGE-06
```

### interlock → dlsPLC.interlock

**Old XML:**
```xml
<interlock.interlock
    addr="07"
    desc="Water Flow Interlocks"
    device="BL04I-VA-VLVCC-01"
    ilk0="I04 Filter" ilk1="X+ Slit Water Flow" ilk2="X- Slit Water Flow"
    ilk3="Y+ Slit Water Flow" ilk4="Y- Slit Water Flow" ilk5="Screen Water Flow"
    ilk6="I04-1 Filter" ilk7="DCM Water Flow"
    ilk8="Unused" ilk9="Unused" ilkA="Unused" ilkB="Unused"
    ilkC="Unused" ilkD="Unused" ilkE="Unused" ilkF="Unused"
    interlock=":INT1" name="INT1" port="ty_40_0"/>
```

**New ioc.yaml** (ilkA–ilkF → ilk10–ilk15; blank fields dropped):
```yaml
- type: dlsPLC.interlock
  addr: 7
  desc: Water Flow Interlocks
  device: BL04I-VA-VLVCC-01
  ilk0: I04 Filter
  ilk1: X+ Slit Water Flow
  ilk2: X- Slit Water Flow
  ilk3: Y+ Slit Water Flow
  ilk4: Y- Slit Water Flow
  ilk5: Screen Water Flow
  ilk6: I04-1 Filter
  ilk7: DCM Water Flow
  interlock: ':INT1'
  port: ty_40_0
```

### overrideRequestMain → dlsPLC.overrideRequestMain

**Old XML:**
```xml
<interlock.overrideRequestMain
    P="BL04I-VA-VLVCC-01" Q=":OVERRIDE"
    addr="08" in="1" out="0"
    name="ITLK" port="ty_40_0"/>
```

**New ioc.yaml** (`outaddr = 08×10 + 0 = 80`; `in`, `out`, `addr`, `name` removed):
```yaml
- type: dlsPLC.overrideRequestMain
  P: BL04I-VA-VLVCC-01
  Q: :OVERRIDE
  outaddr: 80
  port: ty_40_0
```

### overrideRequestIndividual → dlsPLC.overrideRequestIndividual

**Old XML:**
```xml
<interlock.overrideRequestIndividual
    BIT="1" DESC="HFM Piezo Override" FIELD="B"
    OVERRIDE="BL04I-VA-VLVCC-01:OVERRIDE"
    P="BL04I-OP-HFM-01:ILK"
    PRESSURE1="BL04I-VA-GAUGE-04:P" PRESSURE2="BL04I-VA-GAUGE-04:P"
    SETPOINT="500" name="HFMOR"/>
```

**New ioc.yaml** (`FIELD` removed):
```yaml
- type: dlsPLC.overrideRequestIndividual
  BIT: 1
  DESC: HFM Piezo Override
  OVERRIDE: BL04I-VA-VLVCC-01:OVERRIDE
  P: BL04I-OP-HFM-01:ILK
  PRESSURE1: BL04I-VA-GAUGE-04:P
  PRESSURE2: BL04I-VA-GAUGE-04:P
  SETPOINT: 500
```

---

## What xml2yaml handles automatically

The following conversions happen without manual intervention when you run
`builder2ibek xml2yaml`:

| Conversion | Source converter |
|---|---|
| `vacuumValve.vacuumValveRead` → `dlsPLC.read100` (century=0) | `converters/vacuumValve.py` |
| `vacuumValve.vacuumValve` / `vacuumValve_callback` → `dlsPLC.vacValve` with `valve×10` | `converters/vacuumValve.py` |
| `vacuumValve.vacuumValveGroup` → `dlsPLC.vacValveGroup` | `converters/vacuumValve.py` |
| `interlock.interlock` → `dlsPLC.interlock` with hex→int on ilk fields | `converters/interlock.py` |
| `interlock.overrideRequestMain` → `dlsPLC.overrideRequestMain` with outaddr | `converters/interlock.py` |
| `interlock.overrideRequestIndividual` → `dlsPLC.overrideRequestIndividual` (FIELD dropped) | `converters/interlock.py` |
| Blank `ilk*` fields dropped from all dlsPLC entities | `converters/dlsPLC.py` |
| `dlsPLC.fastVacuumChannel` id zero-padded to 2 digits | `converters/dlsPLC.py` |

## What requires manual attention after xml2yaml

| Case | Action |
|---|---|
| `vacuumValve.vacuumValveRead2` | Raises `NotImplementedError`; manually add `dlsPLC.read100` with correct `century` |
| `temperature.*` | Converter is partial WIP; verify output and add `dlsPLC.temperature` / `dlsPLC.read100` manually |
| `vacuumPump.*` | No converter; add `dlsPLC.vacPump` with `valve×10 → addr` manually |
| `flow.flow_asyn` | No converter; add `dlsPLC.flow` with recalculated addresses manually |
| `vacuumValve.vacuumValveBistable` | No converter; add `dlsPLC.vacValveBistable` with `valve×10 → addr` manually |
| `vacuumValve.fvg_asyn` | Remove from ioc.yaml; update GUI to point at gauge interlock bit directly |
| Hostlink → FINS protocol | Update startup script manually; see [Build requirements](#build-requirements) |

---

## Reference: I04 beamline conversion

I04 (`BL04I-VA-IOC-01`) was fully migrated in March 2025 and serves as the
reference example.  The before/after can be seen in the builder2ibek test
samples:

- Before: `tests/samples/BL04I-VA-IOC-01.xml`
- After: `tests/samples/bl04i-va-ioc-01.yaml`
