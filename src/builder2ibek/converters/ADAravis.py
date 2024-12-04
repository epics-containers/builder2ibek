from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = ["aravisGigE", "ADAravis"]
# type in yaml differs from above field in XML
yaml_component = "ADAravis"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "aravisCamera":
        entity.remove("PV_ALIAS")
        if entity["CLASS"] == "AVT_Mako_1_52":
            entity["CLASS"] = "AVT_Mako_G125B"
        if entity["CLASS"] == "AVT_Mako_1_44":
            entity["CLASS"] = "AVT_Mako_G125B"
