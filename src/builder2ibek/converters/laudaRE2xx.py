from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "laudaRE2xx"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    Strip name from laudaRE2xx entities (leaf entities, not cross-referenced).
    """
    entity.remove("name")
