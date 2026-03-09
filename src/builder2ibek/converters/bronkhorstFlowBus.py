from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "bronkhorstFlowBus"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the bronkhorstFlowBus support module
    """

    if entity_type in ["coriFlow"]:
        entity.remove("name")
        if "NODE" in entity:
            entity["NODE"] = str(entity["NODE"])
