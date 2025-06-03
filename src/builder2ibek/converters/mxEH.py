from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mxEH"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mxEH support module
    """

    if entity_type.startswith("auto_"):
        entity.type = entity.type.replace("auto_", "")

    entity.remove("name")
