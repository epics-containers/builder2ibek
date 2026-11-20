from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "gdaPlugins"

# gdaPlugins 1-2's template defaults that differ from the pattern's, which
# follow adUtil
DEFAULTS = {"NCHANS": 20000, "YSIZE": 768}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "gdaPlugins":
        entity.type = "detectorPlugins.gdaPlugins"
        entity.remove("name")
        for param, value in DEFAULTS.items():
            entity.setdefault(param, value)
