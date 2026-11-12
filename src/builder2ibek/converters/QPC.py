"""
QPC converts to the shapes of the ibek-runtime-streamdevice QPC pattern.

The pattern's digitelQpcIonp takes the asyn port and unit of its controller
directly, rather than an object reference to a digitelQpc, so nothing refers to
a digitelQpc by name. Its spon and spoff are strings, passed to the template as
written in the XML.
"""

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "QPC"


def _unit(value) -> str:
    """The 2-hex-digit unit string builder.py makes of a unit attribute."""
    return (f"{int(str(value), 16):02X}")[-2:]


def _controller(ioc: Generic_IOC, name: str):
    """The raw digitelQpc entity named ``name``, or None."""
    for raw in ioc.raw_entities:
        if raw.get("type") == "QPC.digitelQpc" and raw.get("name") == name:
            return raw
    return None


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the QPC support module
    """
    if entity_type == "digitelQpc":
        # the pattern model has no name: ion pumps carry the port and unit
        entity.remove("name")
        unit = entity.get("unit")
        if unit is not None:
            entity.unit = _unit(unit)

    elif entity_type == "digitelQpcIonp":
        entity.remove("name")
        # GUI-only alarm handler tag, not in the pattern model
        entity.remove("alh")

        controller = _controller(ioc, str(entity.get("QPC")))
        entity.remove("QPC")
        if controller is None:
            ioc.extra_warnings.append(
                f"{ioc.source_file.stem}: digitelQpcIonp {entity.get('device')} "
                f"names no digitelQpc controller in this IOC; set its port and unit"
            )
        else:
            entity.port = controller["port"]
            unit = controller.get("unit")
            if unit is not None:
                entity.unit = _unit(unit)

        xml = entity.xml_attributes()
        for setpoint in ("spon", "spoff"):
            if setpoint in xml:
                entity[setpoint] = xml[setpoint]
