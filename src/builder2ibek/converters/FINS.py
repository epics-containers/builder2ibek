from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "FINS"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the FINS support module
    """
    # simulation attribute is a VxWorks builder concept, not needed in ibek
    entity.remove("simulation")
