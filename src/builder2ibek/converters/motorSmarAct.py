from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motorSmarAct"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the motorSmarAct support module
    """
    if entity_type in ["SmaractMcs2Controller"]:
        # name is type: id, keep it for cross-referencing
        pass

    elif entity_type in ["smaractMcs2ExtraTemplate"]:
        entity.remove("name")
