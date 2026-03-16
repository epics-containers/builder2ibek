from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "fw102"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the fw102 filter wheel support module.
    Strips `name` which is a GUI label, not cross-referenced.
    """

    entity.remove("name")
