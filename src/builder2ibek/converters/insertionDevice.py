from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "insertionDevice"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the insertionDevice support module.
    """

    entity.remove("name")

    if entity_type == "insertionDevice4V_generic_DTTemplate":
        if hasattr(entity, "comptable"):
            entity.comptable = str(entity.comptable)
