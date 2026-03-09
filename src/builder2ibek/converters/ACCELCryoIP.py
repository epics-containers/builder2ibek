from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ACCELCryoIP"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the ACCELCryoIP support module.
    Drops the builder object-identity 'name' from all entities —
    neither AccelCryoIp nor auto_ACCELCryoIP_gui is cross-referenced
    by other entities.
    """

    if entity_type in ["AccelCryoIp", "auto_ACCELCryoIP_gui"]:
        entity.remove("name")
