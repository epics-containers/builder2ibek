from builder2ibek.types import Entity, Generic_IOC

xml_component = "aravisGigE"
# type in yaml differs from above field in XML
yaml_component = "ADAravis"

schema = (
    "https://github.com/epics-containers/ioc-adaravis/releases/"
    "download/2023.10.2b2/ibek.ioc.schema.json"
)


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "aravisCamera":
        if entity["CLASS"] == "AVT_Mako_1_52":
            entity["CLASS"] = "AVT_Mako_G125B"
        if entity["CLASS"] == "AVT_Mako_1_44":
            entity["CLASS"] = "AVT_Mako_G125B"
