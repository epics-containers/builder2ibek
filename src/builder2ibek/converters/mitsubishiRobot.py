from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mitsubishiRobot"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mitsubishiRobot support module
    """
    # name is a gui label, not cross-referenced by any entity
    entity.remove("name")
