from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "LeyboldTurbo"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the LeyboldTurbo support module
    """

    # LeyboldPortDriver keeps its name: LeyboldTurboPump.port_driver refers to it
    if entity_type == "LeyboldTurboPump":
        entity.remove("name")
