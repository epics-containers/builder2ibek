from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "digitelSpc"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the digitelSpc support module
    """
    if entity_type == "digitelSpc":
        # transform unit into quoted 2 digit format (only if present)
        unit = entity.get("unit")
        if unit is not None:
            unit_enum = f"{int(unit):02d}"
            entity.unit = unit_enum
    elif entity_type == "digitelSpcIonp":
        entity.remove("name")
