from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "insertionDevice"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the insertionDevice support module.
    """

    # these templates have no records: they exist only for the builder GUI
    if entity_type in ("idcpmuVacuumGui", "idcpmu5VacuumGui"):
        entity.delete_me()
        return

    entity.remove("name")

    if entity_type == "insertionDevice4V_generic_DTTemplate":
        if hasattr(entity, "comptable"):
            entity.comptable = str(entity.comptable)
