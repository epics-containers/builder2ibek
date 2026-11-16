from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import str_or_empty

xml_component = "bronkhorstFlowBus"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the bronkhorstFlowBus support module
    """

    if entity_type in ["coriFlow"]:
        entity.remove("name")
        # an empty NODE stays "", as the builder passed it
        if "NODE" in entity:
            entity["NODE"] = str_or_empty(entity["NODE"])
