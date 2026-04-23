from dataclasses import asdict, dataclass, field
from typing import ClassVar

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "EPICS_BASE"
yaml_component = "epics"


@dataclass
class InterruptVector:
    _interrupt_vector: ClassVar[int] = 1
    type: str = "epics.InterruptVectorVME"
    name: str = field(default_factory=lambda: f"Vec{InterruptVector._interrupt_vector}")

    def __post_init__(self):
        InterruptVector._interrupt_vector += 1

    @classmethod
    def reset(cls):
        cls._interrupt_vector = 1


# a decorator that will be used to add an interrupt vector to the entity
def add_interrupt_vector():
    vec = Entity(asdict(InterruptVector()))
    return vec


# EpicsEnvSet keys that SR-VA.common already emits via its sub_entities.
# When an XML IOC contains SR-VA.common, flat copies of these keys in the XML
# are redundant and produce duplicate epicsEnvSet lines in the generated
# st.cmd — drop them so SR-VA.common is the single source of truth.
_SR_VA_COMMON_ENV_KEYS = frozenset(
    {
        "EPICS_CA_AUTO_ADDR_LIST",
        "EPICS_CA_ADDR_LIST",
        "EPICS_CAS_AUTO_BEACON_ADDR_LIST",
        "EPICS_CAS_BEACON_ADDR_LIST",
    }
)


def _has_sr_va_common(ioc: Generic_IOC) -> bool:
    return any(e.get("type") == "SR-VA.common" for e in ioc.raw_entities)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "EpicsEnvSet":
        if entity["key"] == "EPICS_CA_MAX_ARRAY_BYTES":
            entity.rename("value", "max_bytes")
            entity.remove("key")
            entity.remove("name")
            entity.type = "epics.EpicsCaMaxArrayBytes"
        else:
            entity.rename("key", "name")
            # EpicsEnvSet value must be a string
            entity.value = str(entity.value)
            # remove IOCSH settings as epics-containers makes the iocsh prompt
            if "IOCSH" in entity.name:
                entity.delete_me()
            # STREAM_PROTOCOL_PATH is injected as a default by convert.py
            elif entity.name == "STREAM_PROTOCOL_PATH":
                entity.delete_me()
            elif entity.name in _SR_VA_COMMON_ENV_KEYS and _has_sr_va_common(ioc):
                entity.delete_me()
    elif entity_type == "StartupCommand":
        if entity.post_init:
            entity.type = "epics.PostStartupCommand"
        else:
            entity.type = "epics.StartupCommand"
        entity.remove("post_init")
        entity.remove("name")
        if entity.at_end in ["true", "True"]:
            # TODO get the converter to do this for us
            print(f"Warning: {entity} has at_end==true MOVE IT TO THE END of ioc.yaml")
        entity.remove("at_end")

        if entity.command.startswith("taskDelete") or entity.command.startswith(
            "routeAdd"
        ):
            entity.delete_me()

    elif entity_type == "dbpf":
        entity.value = str(entity.value)
        entity.remove("name")
