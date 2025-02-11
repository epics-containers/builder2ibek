from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import make_bool

xml_component = "DLS8515"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type == "DLS8515":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name

    elif entity_type == "DLS8516":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name

    elif entity_type == "DLS8516channel":
        entity.remove("name")
        entity.fullduplex = make_bool(entity.fullduplex)
