from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "fzoom"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    fzoom entities have name: type: id (used as asyn port name in pre_init),
    so name must be preserved.
    """
    pass
