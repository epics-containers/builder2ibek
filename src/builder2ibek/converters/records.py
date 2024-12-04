from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    # TODO probalby need a better solution to creating raw records - on
    # a case by case basis we should create templates (thus allows documentation)
    # TODO not supporting this yet - just remove it
    entity.delete_me()
