from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "picotechPT104"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the picotechPT104 support module.
    Strips the 'name' parameter which is a GUI label only.
    """

    entity.remove("name")
