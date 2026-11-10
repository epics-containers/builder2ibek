from collections import Counter

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "adPython"

REASON = (
    "adPython is deprecated: port this IOC to ADExternal "
    "(see https://github.com/epics-containers/builder2ibek/issues/173)"
)


def _downstream_note(entity: Entity, ioc: Generic_IOC) -> str:
    """
    Name the entities that take their input from the dropped plugin's port.

    adPython plugins sit in an areaDetector plugin chain; a downstream plugin
    with NDARRAY_PORT set to the dropped port fails ioc.yaml validation
    ("object ... not found") until it is rewired or the IOC is ported.
    """
    port = entity.get("PORT")
    if not port:
        return ""
    users: Counter[str] = Counter()
    for raw in ioc.raw_entities:
        if str(raw.get("type", "")).startswith(f"{xml_component}."):
            continue
        for key, value in raw.items():
            if key != "type" and value == port:
                users[f"{raw['type']} {key}"] += 1
    if not users:
        return f"port {port}: nothing else in the IOC references it"
    named = ", ".join(u if n == 1 else f"{u} (x{n})" for u, n in users.items())
    return (
        f"port {port} is still referenced by: {named}; "
        "rewire or port these by hand, the ioc.yaml fails validation until then"
    )


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the adPython support module

    builder2ibek won't convert adPython: every entity type it defines
    (adPythonPlugin) is left out with a warning naming its port and the
    entities that reference that port.
    """
    ioc.wont_convert(entity, REASON, note=_downstream_note(entity, ioc))
