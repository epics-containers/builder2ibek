from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "utility"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the utility support module
    """

    # pingWait is handled by 'ibek do-wait' in epics-containers
    if entity_type == "pingWait":
        entity.delete_me()
        return

    if entity_type == "directoryWait":
        entity.remove("name")
