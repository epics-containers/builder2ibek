from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ETLdetector"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the ETLdetector support module.
    Drops the builder object-identity 'name' from ETLdetector entities —
    it is a GUI label, not cross-referenced by other entities.
    """

    if entity_type in ["ETLdetector"]:
        entity.remove("name")
        # Ensure addr stays as string (supports hex with 0x prefix)
        if hasattr(entity, "addr"):
            entity.addr = str(entity.addr)
