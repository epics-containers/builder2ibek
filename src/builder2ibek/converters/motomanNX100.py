from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motomanNX100"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    # VAR is used directly in PV names (e.g. P$(VAR):X, D$(VAR), IO$(VAR))
    # so it must always be a string to preserve any leading zeros or formatting.
    if entity.VAR is not None:
        entity.VAR = str(entity.VAR)
