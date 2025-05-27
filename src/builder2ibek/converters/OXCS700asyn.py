from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "OXCS700asyn"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type in "OXCS700asyn":
        entity.remove("name")
        entity.remove("DISABLE_COMMS")
        if not hasattr(entity, "Q"):
            entity.Q = ""
