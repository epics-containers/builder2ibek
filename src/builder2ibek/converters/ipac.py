from enum import Enum

from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import make_bool

xml_component = "ipac"


class Direction(Enum):
    Input = 0
    Output = 1
    Mixed = 2


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type == "Hy8002":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name

    if entity_type == "Hy8001":
        entity.direction = Direction(entity.direction).name
        entity.remove("name")
        for key in ["invertin", "invertout", "ip_support"]:
            entity[key] = make_bool(entity[key])
