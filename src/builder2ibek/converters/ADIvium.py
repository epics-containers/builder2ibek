from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ADIvium"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the ADIvium support module.
    Ivium.name is an id cross-referenced by IviumPort and IviumChannel,
    so it must be kept.
    """
    pass
