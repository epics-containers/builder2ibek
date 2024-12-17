from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "autosave"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type == "Autosave":
        entity.rename("iocName", "P")
        entity.P += ":"
        # TODO if this is a motor then set entity.postions_req_period = 5
        entity.remove("bl")
        entity.remove("ip")
        entity.remove("name")
        entity.remove("path")
        entity.remove("server")
