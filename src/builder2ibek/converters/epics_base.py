import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import str_or_empty

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


# iocsh db* commands that act on loaded records (dbpf, dbgf, dbpr, dbtr ...);
# dbLoadRecords and the like do not
_NEEDS_RECORDS = re.compile(r"\s*db(?!Load)\w*\b")


def builder_bool(entity: Entity, name: str, default: bool) -> bool:
    """
    A bool argument as the builder read its XML attribute: absent is the
    default; "" and "false" (any case) are False; anything else is True
    """
    value = entity.xml_attributes().get(name)
    if value is None:
        return default
    return value.lower() not in ("", "false")


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
            # EpicsEnvSet value must be a string. ibek writes it unquoted, and
            # iocsh's epicsEnvSet rejects a missing value, so an empty one is
            # written as "", which sets the variable to the empty string
            entity.value = str_or_empty(entity.value) or '""'
            # remove IOCSH settings as epics-containers makes the iocsh prompt
            if "IOCSH" in entity.name:
                entity.delete_me()
            # STREAM_PROTOCOL_PATH is injected as a default by convert.py
            elif entity.name == "STREAM_PROTOCOL_PATH":
                entity.delete_me()
            elif entity.name in _SR_VA_COMMON_ENV_KEYS and _has_sr_va_common(ioc):
                entity.delete_me()
    elif entity_type == "StartupCommand":
        post_init = builder_bool(entity, "post_init", False)
        at_end = builder_bool(entity, "at_end", True)
        if post_init:
            entity.type = "epics.PostStartupCommand"
        else:
            entity.type = "epics.StartupCommand"
        if at_end:
            # The builder prints an at_end command after every device's
            # commands: before iocInit, after the databases are loaded; or
            # straight after iocInit, before the devices' post-init commands.
            # ibek emits commands in entity order, so placing the entity last
            # (or first, after iocInit) gives the same order, except that a
            # pre-init command runs before dbLoadRecords.
            if post_init:
                entity.place_first()
            else:
                entity.place_last()
                if _NEEDS_RECORDS.match(entity.command or ""):
                    ioc.extra_warnings.append(
                        f"{Path(ioc.source_file).stem}: StartupCommand "
                        f"{entity.command!r} runs before dbLoadRecords, as ibek "
                        f"has no place between dbLoadRecords and iocInit: make "
                        f"it post_init if it needs the records"
                    )
        entity.remove("post_init")
        entity.remove("name")
        entity.remove("at_end")

        if entity.command.startswith("taskDelete") or entity.command.startswith(
            "routeAdd"
        ):
            entity.delete_me()

    elif entity_type == "dbpf":
        # dbpf "PV" "" puts an empty string, as the XML asks
        entity.value = str_or_empty(entity.value)
        entity.remove("name")
