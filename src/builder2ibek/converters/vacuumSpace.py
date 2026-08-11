from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumSpace"

# Prefixes for indexed device parameters.  The XML / builder uses 0-based
# indices (gauge0..7) but the ibek entity model and group templates use
# 1-based indices (gauge1..8).  The converter renames them.
_DEVICE_PREFIXES = ["gauge", "ionp", "img", "pirg", "valve"]

# Parameters whose values are builder short-names (e.g. "IONP4") that must be
# translated to the device PV name (e.g. "BL19I-VA-IONP-04").  After renaming,
# these are 1-indexed, and a space can carry up to 8 of each.
_OBJECT_PARAMS = [f"{prefix}{i}" for prefix in _DEVICE_PREFIXES for i in range(1, 9)]

# Gauge entity types keyed by dom + id rather than by a device attribute.  Their
# records are named $(dom)-VA-GAUGE-$(id) - see mks937[ab]Gauge.template.
_GAUGE_TYPES = {
    "mks937a.mks937aGauge",
    "mks937a.mks937aGaugeEGU",
    "mks937b.mks937bGauge",
    "mks937b.mks937bGaugeEGU",
}


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

    vacuumSpace's gauge/ionp/img/pirg/valve parameters are plain strings that get
    rendered straight into db macros (`field(INPA, "$(gauge1):SEL MS")` and
    friends), so they must always hold the real PV.  A short-name that survives
    into the substitutions produces links to PVs like "GAUGE1:SEL" that can never
    connect - which is what builder avoids by resolving the reference itself.

    This is true even for entities whose 'name' ibek keeps as its `type: id`
    (mks937[ab] gauges, imgs and pirgs).  Being an ibek id only matters for
    parameters declared `type: object`; none of vacuumSpace's device parameters
    are, so the id is never resolved for us and the short-name must be
    substituted here.
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


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the vacuumSpace support module
    """

    # remove GUI only parameters (except those that use name for object ref)
    if entity_type == "spaceTemplate":
        entity.remove("name")

    elif entity_type in ["space", "space_b"]:
        # Rename 0-indexed params (gauge0..7) to 1-indexed (gauge1..8) to
        # match the ibek entity model and group template macro names.
        for prefix in _DEVICE_PREFIXES:
            for i in range(7, -1, -1):  # reverse to avoid key collision
                val = entity.get(f"{prefix}{i}")
                if val is not None:
                    entity[f"{prefix}{i + 1}"] = val
                    entity.remove(f"{prefix}{i}")

        # Translate builder short-names to ibek device PV names for any
        # object-reference parameters that need it.
        name_map = _build_name_map(ioc)
        for param in _OBJECT_PARAMS:
            val = entity.get(param)
            if val and str(val) in name_map:
                entity[param] = name_map[str(val)]
