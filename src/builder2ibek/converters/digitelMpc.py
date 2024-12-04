from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "digitelMpc"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type in ["digitelMpc", "digitelMpcTsp"]:
        # transform unit into quoted 2 digit format
        unit = int(entity.get("unit"))  # type: ignore
        unit_enum = f"{unit:02d}"
        entity.unit = unit_enum
