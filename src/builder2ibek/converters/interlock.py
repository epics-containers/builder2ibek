from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import hex_to_int

xml_component = "interlock"

# records the port names of the read100 entities keyed by name
read100Objects: dict[str, str] = {}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the interlock support module

    This module gets converted to dlsPLC equivalents
    """

    if entity_type == "interlock":
        entity.type = "dlsPLC.interlock"
        entity.addr = str(entity.addr)  # TODO make int in dlsPLC.ibek.support.yaml
        # entity.remove("name")

        hex_to_int(entity, "ilk")
