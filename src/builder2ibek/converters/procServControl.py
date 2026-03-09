from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "procServControl"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the procServControl support module
    """

    if entity_type in ["procServControl", "procServControlGui"]:
        entity.remove("name")
