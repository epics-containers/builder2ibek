from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "hidenRGA"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    entity.remove("name")
