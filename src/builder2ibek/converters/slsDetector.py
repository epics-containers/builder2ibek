from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import make_bool

xml_component = "slsDetector"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the slsDetector support module
    """

    if entity_type == "slsDetector":
        entity.remove("name")
        if "cacheConfigFile" in entity:
            entity["cacheConfigFile"] = make_bool(entity["cacheConfigFile"])
