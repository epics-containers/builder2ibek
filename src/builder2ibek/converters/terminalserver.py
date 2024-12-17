from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "terminalServer"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the terminalServer module
    """

    if entity_type == "Moxa":
        if entity.NCHANS > 16:
            entity.type = "terminalServer.Moxa32"
        else:
            entity.type = "terminalServer.Moxa16"
