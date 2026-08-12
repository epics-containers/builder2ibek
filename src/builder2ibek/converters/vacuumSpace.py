from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumSpace"

# Gauge entity types keyed by dom + id rather than by a device attribute.  Their
# records are named $(dom)-VA-GAUGE-$(id) - see mks937[ab]Gauge.template.
_GAUGE_TYPES = {
    "mks937a.mks937aGauge",
    "mks937a.mks937aGaugeEGU",
    "mks937b.mks937bGauge",
    "mks937b.mks937bGaugeEGU",
}

# builder's `space` and `space_b` are helpers, not templates: _make_groups() in
# vacuumSpace/etc/builder.py counts the devices of each type the space was given
# and only then decides what to create.
#
#   0 devices -> a dummy at <device>:XXXG, and the space links to that
#   1 device  -> NO group at all; the space links straight at the device
#   >1        -> a group at <device>:XXXG, and the space links to that
#
# ibek entity models cannot express that, so we expand a space into the same set
# of entities builder would have created and emit a plain space[_b]Template.
# Getting it wrong is not cosmetic - a space linked at a :XXXG group that was
# never instantiated is permanently disconnected at runtime.

# Group templates and dummies per component, keyed by space flavour.  `space`
# uses the mks937a gauges, `space_b` the mks937b ones.  A gauge has no dummy:
# builder asserts if a space is defined without one.
_MODELS = {
    "space": {
        "gauge": ("mks937a.mks937aGaugeGroup", None),
        "img": ("mks937a.mks937aImgGroup", "mks937a.mks937aImgDummy"),
        "ionp": ("digitelMpc.digitelMpcIonpGroup", "digitelMpc.dummyIonp"),
        "pirg": ("mks937a.mks937aPirgGroup", "mks937a.mks937aPirgDummy"),
        "valve": ("dlsPLC.vacValveGroup", "dlsPLC.dummyValve"),
    },
    "space_b": {
        "gauge": ("mks937b.mks937bGaugeGroup", None),
        "img": ("mks937b.mks937bImgGroup", "mks937b.mks937bImgDummy"),
        "ionp": ("digitelMpc.digitelMpcIonpGroup", "digitelMpc.dummyIonp"),
        "pirg": ("mks937b.mks937bPirgGroup", "mks937b.mks937bPirgDummy"),
        "valve": ("dlsPLC.vacValveGroup", "dlsPLC.dummyValve"),
    },
}

# builder hardcodes the delay it passes to each group it creates.  The gauge and
# pirg groups get none - they keep their template default.
_GROUP_DELAY = {"ionp": 4, "img": 2, "valve": 1}

# The number of devices of each type a space can be given.  builder's numobs is
# 4, but the group templates take 8 slots.
_MAX_DEVICES = 8


def _raw_device(raw: dict) -> str | None:
    """
    The device PV name that a raw builder entity's records are created under.
    """
    device = raw.get("device")
    if device:
        return str(device)

    if raw.get("type") in _GAUGE_TYPES:
        dom, gauge_id = raw.get("dom"), raw.get("id")
        if dom and gauge_id is not None:
            return f"{dom}-VA-GAUGE-{int(gauge_id):02d}"

    return None


def _build_name_map(ioc: Generic_IOC) -> dict[str, str]:
    """
    Map builder short-name -> device PV name for every raw entity a vacuum space
    can cross-reference.

    A space's gauge/ionp/img/pirg/valve parameters are plain strings that get
    rendered straight into db macros (`field(INPA, "$(gauge1):SEL MS")` and
    friends), so they must always hold the real PV.  A short-name that survives
    into the substitutions produces links to PVs like "GAUGE1:SEL" that can never
    connect - which is what builder avoids by resolving the reference itself.

    This is true even for entities whose 'name' ibek keeps as its `type: id`
    (mks937[ab] gauges, imgs and pirgs).  Being an ibek id only matters for
    parameters declared `type: object`; none of these are, so the id is never
    resolved for us and the short-name must be substituted here.
    """
    mapping: dict[str, str] = {}
    for raw in ioc.raw_entities:
        name = raw.get("name")
        if not name:
            continue
        device = _raw_device(raw)
        if device and str(name) != device:
            mapping[str(name)] = device
    return mapping


def _take_devices(entity: Entity, component: str, name_map: dict[str, str]):
    """
    Pop a space's <component>0..7 parameters and return the device PV names it
    was given, in order and with any gaps closed up.

    builder builds this list from `sorted(args.keys())`, so a space given gauge0
    and gauge2 (but no gauge1) ends up with a two device gauge group, not a
    three device one with a hole in the middle.
    """
    devices = []
    for i in range(_MAX_DEVICES):
        value = entity.get(f"{component}{i}")
        entity.remove(f"{component}{i}")
        if value:
            devices.append(name_map.get(str(value), str(value)))
    return devices


def _expand_space(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    Replace a `space` / `space_b` helper with the group and dummy entities
    builder would have created, plus the space[_b]Template that links them.
    """
    name_map = _build_name_map(ioc)

    for component, (group_type, dummy_type) in _MODELS[entity_type].items():
        devices = _take_devices(entity, component, name_map)
        group_device = f"{entity.device}:{component.upper()}G"

        if len(devices) == 1:
            # no group - the space template links straight at the device
            entity[component] = devices[0]
            continue

        entity[component] = group_device

        if not devices:
            if dummy_type is None:
                raise ValueError(
                    f"{entity.device}: vacuum space defined with missing {component}"
                )
            entity.add_entity({"type": dummy_type, "device": group_device})
            continue

        # builder pads the group's 8 slots with the first device
        padded = (devices + [devices[0]] * _MAX_DEVICES)[:_MAX_DEVICES]
        group = {"type": group_type, "device": group_device}
        if component in _GROUP_DELAY:
            group["delay"] = _GROUP_DELAY[component]
        group.update({f"{component}{i + 1}": d for i, d in enumerate(padded)})
        entity.add_entity(group)

    entity.type = f"vacuumSpace.{entity_type}Template"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the vacuumSpace support module
    """
    if entity_type in _MODELS:
        _expand_space(entity, entity_type, ioc)
