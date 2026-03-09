from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL15I-BUILDER"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for BL15I-BUILDER module.

    BL15I-BUILDER defines beamline-specific AutoSubstitution templates
    that are not available in Generic IOCs. Skip them.
    """
    entity.delete_me()
