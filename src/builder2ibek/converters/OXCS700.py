from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "OXCS700"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type in "OXCS700":
        # convert this to the newer asyn based support module
        entity.type = "OXCS700asyn.OXCS700asyn"
        entity.remove("name")
        entity.remove("DISABLE_COMMS")
        if not hasattr(entity, "Q") or not entity.Q:
            entity.Q = ""
