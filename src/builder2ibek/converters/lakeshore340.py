from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "lakeshore340"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    lakeshore340 entities have name: type: id (used in template GUI macros
    and PVI prefix), so name must be preserved.
    """
    pass
