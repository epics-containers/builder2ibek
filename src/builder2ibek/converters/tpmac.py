from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "tpmac"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the tpmac support module
    """

    if entity_type == "pmacAsynIPPort":
        entity.type = "pmac.pmacAsynIPPort"
    elif entity_type == "pmacDisableLimitsCheck":
        entity.type = "pmac.pmacDisableLimitsCheck"
    elif entity_type == "GeoBrick":
        entity.type = "pmac.GeoBrick"
        entity.rename("Port", "pmacAsynPort")
        for check_entity in ioc.raw_entities:
            check_entity = Entity(**check_entity)
            if (
                check_entity.type.endswith("pmacStatus")
                and check_entity.PORT == entity.pmacAsynPort
            ):
                entity.P = check_entity.DEVICE
