from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "OXCryo"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    Convert OXCryo entities to the newer oxCryo support module.
    """

    if entity_type == "OXCS700":
        entity.type = "oxCryo.OXCS700"
        entity.remove("name")
        # entity.remove("DISABLE_COMMS")
        # if not hasattr(entity, "Q") or not entity.Q:
        #     entity.Q = ""

    elif entity_type == "OXNH700":
        entity.type = "oxCryo.OXNH700"
        entity.remove("name")

    elif entity_type == "OXCB700":
        entity.type = "oxCryo.OXCB700"
        entity.remove("name")

    elif entity_type == "OXCB800":
        entity.type = "oxCryo.OXCB800"
        entity.remove("name")
