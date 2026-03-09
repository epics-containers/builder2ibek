from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "lakeshore336"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the lakeshore336 support module.
    Strips 'name' which is a GUI label, not cross-referenced.
    """

    if entity_type == "lakeshore336":
        entity.remove("name")
        # SCAN and TEMPSCAN are EPICS scan rate strings but XML has bare integers
        for field in ["SCAN", "TEMPSCAN"]:
            if field in entity:
                entity[field] = str(entity[field])
