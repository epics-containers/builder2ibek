from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumSpace"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the vacuumSpace support module
    """

    # remove GUI only parameters (except those that use name for object ref)
    if entity_type == "spaceTemplate":
        entity.remove("name")
