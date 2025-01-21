from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import int_to_hertz

xml_component = "Hy8401ip"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the Hy8401 support module
    """

    if entity_type == "Hy8401":
        entity.remove("name")
        int_to_hertz(entity, "clockRate")

        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
