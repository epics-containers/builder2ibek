from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "TimingTemplates"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    if entity_type == "generalTimeTemplate":
        entity.type = "TimingTemplates.GeneralTime"
        entity.remove("name")

    elif entity_type == "evr_alive":
        entity.type = "TimingTemplates.EvrAlive"
        entity.remove("name")

    elif entity_type == "defaultEVR":
        entity.type = "TimingTemplates.DefaultEVR"
        entity.remove("name")
