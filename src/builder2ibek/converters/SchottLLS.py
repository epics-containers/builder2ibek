from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "SchottLLS"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type in "auto_SchottLLS":
        entity.remove("name")
        entity.type = "SchottLLS.SchottLLS"
        if not hasattr(entity, "D") or not entity.D:
            entity.D = ""
