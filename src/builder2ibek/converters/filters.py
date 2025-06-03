from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "filters"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the filters support module
    """

    if entity_type == "auto_pneuCombinations":
        entity.type = "filters.pneuCombinations"

    entity.remove("name")
