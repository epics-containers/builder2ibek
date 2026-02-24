from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "temperature"

# records the port names of the read100 entities keyed by name
read100Objects = {}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the temperature support module

    THIS MODULE GETS CONVERTED TO dlsPLC EQUIVALENTS
    See https://confluence.diamond.ac.uk/x/i4kuAw

    TODO this is WIP
    """

    if entity_type == "temperaturePLC":
        # record the port name of this entity
        read100Objects[entity.name] = entity.port
