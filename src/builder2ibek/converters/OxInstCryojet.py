from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "OxInstCryojet"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the OxInstCryojet support module

    No entity of this module is referenced by another, so name (a GUI label)
    is dropped from all of them.
    """
    entity.remove("name")
    if entity_type == "ILM201":
        # alarm handler tag, read only by the template's comments; not in the
        # pattern model
        entity.remove("alh")
