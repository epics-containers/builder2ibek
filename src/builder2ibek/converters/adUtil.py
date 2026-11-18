from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "adUtil"

schema = ""


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "gdaPlugins":
        # the runtime pattern takes the builder object's parameters and
        # defaults (adUtil 2-20 and later) as they are; nothing refers to name
        entity.type = "detectorPlugins.gdaPlugins"
        entity.remove("name")
