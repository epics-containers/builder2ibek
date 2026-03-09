from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "eurotherm2k"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the eurotherm2k support module
    """

    if entity_type in ["eurotherm2k"]:
        entity.remove("name")
