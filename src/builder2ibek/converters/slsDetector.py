from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "slsDetector"
yaml_component = "slsDetector"

# builder defaults of the attributes the ibek-support model requires
REQUIRED_DEFAULTS = {"detectorIndex": 0, "numModules": 1, "BUFFERS": 50, "MEMORY": 0}

OLD_API = (
    "this slsDetector takes useReceiver, the API of slsDetector 2-0dls1; "
    "ibek-support builds a slsDetectorPackage whose slsDetectorConfig takes "
    "numModules instead"
)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the slsDetector support module
    """

    if entity_type == "slsDetector":
        if "useReceiver" in entity:
            ioc.wont_convert(entity, OLD_API)
            return
        entity.type = "slsDetector.slsDetectorConfigure"
        entity.remove("name")
        # some builder versions spell these differently
        entity.rename("configFileName", "configFile")
        entity.rename("detectorId", "detectorIndex")
        # the ibek-support model reads configFile as given: no cached copy
        entity.remove("cacheConfigFile")
        entity.remove("iocName")
        for attr, default in REQUIRED_DEFAULTS.items():
            if entity.get(attr) in (None, ""):
                entity[attr] = default
