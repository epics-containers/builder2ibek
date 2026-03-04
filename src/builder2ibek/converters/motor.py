from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motor"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the motor support module.

    Strips 'name' from leaf entities like basic_asyn_motor where it is just
    a GUI label, not cross-referenced by any other entity.
    """

    if entity_type in ["basic_asyn_motor"]:
        entity.remove("name")
