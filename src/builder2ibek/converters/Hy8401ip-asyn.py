from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import int_to_hertz

xml_component = "Hy8401ip-asyn"

_scanMode_map = {0: "Continuous", 1: "Triggered", 2: "Gated"}
_externalClock_map = {0: "Internal", 1: "External"}
_fastADC_map = {0: "Slow", 1: "Fast"}


def _int_to_enum(entity: Entity, key: str, mapping: dict):
    if key in entity:
        val = entity[key]
        if isinstance(val, int) and val in mapping:
            entity[key] = mapping[val]


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the Hy8401ip-asyn support module
    """

    if entity_type == "Hy8401Asyn":
        int_to_hertz(entity, "clockRate")
        _int_to_enum(entity, "scanMode", _scanMode_map)
        _int_to_enum(entity, "externalClock", _externalClock_map)
        _int_to_enum(entity, "fastADC", _fastADC_map)

        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name

    elif entity_type in ["Channel_ai", "Channel_waveform"]:
        entity.remove("name")
