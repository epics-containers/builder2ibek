from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "digitelMpc"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type in ["digitelMpc", "digitelMpcTsp"]:
        # transform unit into quoted 2 digit format (only if present)
        unit = entity.get("unit")
        if unit is not None:
            unit_enum = f"{int(unit):02d}"
            entity.unit = unit_enum

    if entity_type in [
        "digitelMpcIonp",
        "digitelMpcIonpGroup",
        "dummyIonp",
        "digitelMpcTsp",
    ]:
        entity.remove("name")
