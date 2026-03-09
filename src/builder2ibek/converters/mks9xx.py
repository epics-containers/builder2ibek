from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mks9xx"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mks9xx support module
    """

    if entity_type == "mks9xxGauge":
        entity.remove("name")
        # Zero-pad id to 2 digits as builder.py does: "%02d" % int(id)
        if "id" in entity:
            entity["id"] = f"{int(entity['id']):02d}"
