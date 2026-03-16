from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "smaractEcm"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the smaractEcm support module
    """

    if entity_type == "SmaractSmarpodAxis":
        entity.remove("name")

    if entity_type == "Smarpod":
        # resolution is type: str but XML parses scientific notation as float
        if hasattr(entity, "resolution") and entity.resolution is not None:
            entity.resolution = str(entity.resolution)
