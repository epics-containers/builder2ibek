from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mrfioc2"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mrfioc2 support module.
    Strips the 'name' attribute which is a GUI label, not cross-referenced.
    """

    if entity_type in ["mrfioc2", "defaultPCIe"]:
        entity.remove("name")
