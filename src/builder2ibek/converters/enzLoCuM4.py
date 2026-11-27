from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "enzLoCuM4"

# Templates that some enzLoCuM4 releases expose only as builder auto_ classes, and
# that the pattern models under the template name, with the same parameters
NAMED_TEMPLATES = {"enzLoCuM4Readback"}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the enzLoCuM4 support module
    """
    if entity_type.startswith("auto_") and entity_type[5:] in NAMED_TEMPLATES:
        entity_type = entity_type[5:]
        entity.type = f"{xml_component}.{entity_type}"

    # no enzLoCuM4 entity is referred to by another, so name is GUI-only
    entity.remove("name")

    if entity_type == "enzLoCuM4" and "adr" in entity:
        # Ensure adr stays as string (preserves leading zeros e.g. "01")
        adr = str(entity.adr)
        # an empty address stays "", as the builder passed it: padding
        # it would invent address "00"
        entity.adr = adr.zfill(2) if adr else adr
