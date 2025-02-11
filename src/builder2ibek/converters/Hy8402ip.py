from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "Hy8402ip"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the Hy8402 support module
    """

    if entity_type == "Hy8402":
        entity.remove("name")

        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
