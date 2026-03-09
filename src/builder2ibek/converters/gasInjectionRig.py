from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "gasInjectionRig"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the gasInjectionRig support module.
    Drops the builder object-identity 'name' from auto_I11LowPressure —
    it is a leaf entity not cross-referenced by other entities.
    """

    if entity_type == "auto_I11LowPressure":
        entity.remove("name")
