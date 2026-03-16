from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ADOdinTristan"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the ADOdinTristan support module.
    Strips name from leaf entities that are not cross-referenced.
    """

    if entity_type in ["TristanControlSimulator", "TristanOdinLogConfig"]:
        entity.remove("name")
