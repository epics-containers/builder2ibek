from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "QPC"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the QPC support module
    """
    if entity_type == "digitelQpc":
        # Coerce unit to 2-hex-digit string (matches builder.py behaviour)
        unit = entity.get("unit")
        if unit is not None:
            entity.unit = (f"{int(unit, 16):02X}")[-2:]

    if entity_type == "digitelQpcIonp":
        # Leaf entity — drop the non-cross-referenced name
        entity.remove("name")
