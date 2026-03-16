from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumSpace"

# Prefixes for indexed device parameters.  The XML / builder uses 0-based
# indices (gauge0..7) but the ibek entity model and group templates use
# 1-based indices (gauge1..8).  The converter renames them.
_DEVICE_PREFIXES = ["gauge", "ionp", "img", "pirg", "valve"]

# Parameters whose values are object references that may need translating
# from builder short-names (e.g. "IONP4") to ibek device PV names
# (e.g. "BL19I-VA-IONP-04").  After renaming, these are 1-indexed.
_OBJECT_PARAMS = [
    "ionp1",
    "ionp2",
    "ionp3",
    "img1",
    "img2",
    "img3",
    "pirg1",
    "pirg2",
    "pirg3",
    "valve1",
    "valve2",
    "valve3",
]


def _build_name_map(ioc: Generic_IOC) -> dict[str, str]:
    """
    Scan raw_entities for any entity that has both a builder 'name' attribute
    and a 'device' attribute.  Returns a mapping name→device so that short
    builder cross-reference names can be resolved to ibek entity ids.

    This is needed because ibek registers some entities under their 'device'
    PV name (type: id = device), but the vacuumSpace XML references them by
    the builder 'name' attribute (e.g. IONP4 instead of BL19I-VA-IONP-04).

    Some modules (e.g. mks937b) retain 'name' as the ibek id rather than
    'device'.  Those entries must NOT be translated: the builder short-name
    IS the correct ibek id.  We detect them by checking whether the 'name'
    value still appears in the already-converted ioc.entities — if it does,
    that entity registered under its 'name', so skip it.
    """
    # Names that are still present in converted entities are ibek ids themselves.
    kept_names: set[str] = set()
    for ent in ioc.entities:
        n = ent.get("name")
        if n:
            kept_names.add(str(n))

    mapping: dict[str, str] = {}
    for raw in ioc.raw_entities:
        name = raw.get("name")
        device = raw.get("device")
        if name and device and name != device and str(name) not in kept_names:
            mapping[str(name)] = str(device)
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
