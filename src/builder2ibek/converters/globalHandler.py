from builder2ibek.types import Entity, Generic_IOC

xml_component = "global"


def globalHandler(entity: Entity, entity_type: str, ioc: Generic_IOC, target_handler=None):
    entity.remove("gda_name")
    entity.remove("gda_desc")

    if target_handler:
        return target_handler(entity, entity_type, ioc)
    