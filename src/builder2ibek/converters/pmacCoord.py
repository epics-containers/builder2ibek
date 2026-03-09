"""
Converter handler for the pmacCoord support module.
"""

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "pmacCoord"

_cs_ref_counter = 0


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmacCoord support module.
    """
    global _cs_ref_counter

    if entity_type == "CS":
        # Rename Controller -> PmacController for compatibility with pmac.CS
        entity.rename("Controller", "PmacController")
        # Inject the Ref counter (global sequence number for coord systems)
        entity.Ref = _cs_ref_counter
        _cs_ref_counter += 1
