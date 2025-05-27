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


# easier to use than the enum as can be copied verbatim from builder.py
direction_8005 = ["inputs", "low out/high in", "low in/high out", "outputs"]
ipslot_str = ["A", "B", "C", "D"]
debrate_8005 = ["1KHz", "100Hz", "200Hz", "500Hz"]
pwidth_8005 = [
    "1msec",
    "10msec",
    "100msec",
    "1sec",
    "2sec",
    "5sec",
    "10sec",
    "20sec",
    "50sec",
    "100sec",
]
scanrate_8005 = ["1KHz", "10KHz", "100KHz", "1MHz"]


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type == "Hy8001":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
        entity.direction = Direction(entity.direction).name
        for key in ["invertin", "invertout", "ip_support"]:
            if key in entity:
                entity[key] = make_bool(entity[key])
    elif entity_type == "Hy8005":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
    elif entity_type == "Hy8005_Channel":
        entity.ipslot = ipslot_str[entity.ipslot or 0]
        entity.debrate = debrate_8005[entity.debrate or 0]
        entity.pwidth = pwidth_8005[entity.pwidth or 0]
        entity.scanrate = scanrate_8005[entity.scanrate or 0]
        entity.direction = direction_8005[entity.direction or 0]
