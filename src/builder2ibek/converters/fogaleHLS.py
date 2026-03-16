from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "fogaleHLS"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the fogaleHLS support module.
    Strips name (GUI label only, not cross-referenced).
    """

    if entity_type == "fogaleHLS":
        entity.remove("name")
