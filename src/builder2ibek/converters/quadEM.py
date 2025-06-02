from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "quadEM"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the quadEM support module
    """

    # We are combining arrayPlugins and statPlugins
    # into one Plugins object
    if entity_type == "arrayPlugins":
        entity.delete_me()
    elif entity_type == "statPlugins":
        entity.type = "quadEM.Plugins"
        entity.PORTPREFIX = entity.PORTPREFIX.replace(".STATS", "")
        entity.remove("P")
    elif entity_type == "quadEM_TimeSeries":
        entity.remove("P")
        entity.remove("R")
