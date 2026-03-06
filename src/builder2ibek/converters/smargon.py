from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "smargon"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the smargon support module.
    """

    if entity_type in ["fastGridScans", "robotInterlocks", "omegaProtection"]:
        entity.remove("name")
