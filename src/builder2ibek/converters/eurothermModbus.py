from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "eurothermModbus"

_modbus_prefix_index = 1


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the eurothermModbus module.
    Strips name (GUI label), generates modbus_prefix with a global counter.
    """
    global _modbus_prefix_index

    if entity_type in [
        "Eurotherm2K",
        "Eurotherm3K",
        "Eurotherm3KPIDselect",
        "Eurotherm3Krtu",
        "Eurotherm3KrtuPIDselect",
    ]:
        entity.remove("name")
        entity.modbus_prefix = f"EURTHM_MB_{_modbus_prefix_index}"
        _modbus_prefix_index += 1
