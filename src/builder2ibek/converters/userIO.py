from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "userIO"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the userIO support module
    """
    # name is a GUI label, not needed in ibek (no entity cross-references it)
    entity.remove("name")

    # Some str-typed params in support YAML get parsed as int/float by XML.
    # Only coerce fields that are actually type: str (not float/int).
    str_fields = ["LINR", "OUT", "INP", "EGU"]
    for field in str_fields:
        val = entity.get(field)
        if val is not None and not isinstance(val, str):
            entity[field] = str(val)
