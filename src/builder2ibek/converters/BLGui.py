from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BLGui"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    BLGui entities are legacy EDM synoptic display support and have no
    equivalent in epics-containers. Drop all of them.
    """
    entity.delete_me()
