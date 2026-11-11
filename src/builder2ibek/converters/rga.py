from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "rga"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the rga support module
    """

    # rgaGui.template has no records: it exists only for the builder GUI
    if entity_type == "rgaGuiTemplate":
        entity.delete_me()
    elif entity_type == "rga":
        entity.remove("name")
