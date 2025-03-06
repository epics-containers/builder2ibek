from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ffmpegServer"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the ffmpegServer support module
    """

    if entity_type == "ffmpegFile":
        # remove unecessary parameters
        entity.remove("ADDR")
        entity.remove("BUFFERS")
        entity.remove("ENABLED")
        entity.remove("MEMORY")
        entity.remove("TIMEOUT")

    if entity_type == "ffmpegStream":
        # remove unecessary parameters
        entity.remove("ADDR")
        entity.remove("ENABLED")
        entity.remove("TIMEOUT")
