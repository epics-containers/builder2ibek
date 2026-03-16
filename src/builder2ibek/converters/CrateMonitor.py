from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "CrateMonitor"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the CrateMonitor support module.
    Strips 'name' — it is a GUI label, not cross-referenced by other entities.
    """

    entity.remove("name")
