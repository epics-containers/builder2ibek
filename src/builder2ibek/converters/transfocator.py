from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "transfocator"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the transfocator support module.
    Drops the 'name' parameter which is a GUI label, not cross-referenced.
    """

    if entity_type in ["transfocator", "BL04I_beamsizeCalc"]:
        entity.remove("name")
