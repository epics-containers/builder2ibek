from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL11I"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL11I support module
    """

    if entity_type in [
        "BL11I_cryo_rocker",
        "maxonDEC505",
        "auto_BL11I_furnace_spinner",
        "auto_BL11I_serial_trigger",
    ]:
        entity.remove("name")
