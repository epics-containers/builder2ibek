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
        hex_to_int(entity, "ilk")

    if entity_type == "overrideRequestMain":
        entity.type = "dlsPLC.overrideRequestMain"
        # https://confluence.diamond.ac.uk/x/i4kuAw#:~:text=addr%2C%20in%2C%20and,is%20outaddr%2D1
        entity.outaddr = int(entity.addr) * 10 + int(entity["in"])
        entity.remove("in")
        entity.remove("out")
        entity.remove("addr")
        entity.remove("name")

    if entity_type == "overrideRequestIndividual":
        entity.type = "dlsPLC.overrideRequestIndividual"
        entity.remove("FIELD")
