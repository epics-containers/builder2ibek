from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL21I"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL21I support module
    """

    if entity_type in ["SCM10", "SMPLTempsController", "M5LimitLatch", "M5LimitStop"]:
        entity.remove("name")
