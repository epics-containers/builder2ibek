from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.converters.globalHandler import globalHandler

xml_component = "autosave"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    # TODO not supporting this yet - just remove it
    entity.delete_me()
