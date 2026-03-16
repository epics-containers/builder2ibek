from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "enzLoCuM4"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the enzLoCuM4 support module
    """

    if entity_type in ["enzLoCuM4"]:
        entity.remove("name")
        # Ensure adr stays as string (preserves leading zeros e.g. "01")
        if hasattr(entity, "adr"):
            entity.adr = str(entity.adr).zfill(2)
