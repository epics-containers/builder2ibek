from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "userIO"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the userIO support module
    """
    # name is a GUI label, not needed in ibek (no entity cross-references it)
    entity.remove("name")
