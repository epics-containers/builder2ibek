from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumValve"

# records the port names of the read100 entities keyed by name
read100Objects = {}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the vacuumValve support module

    This module gets converted to dlsPLC equivalents
    """

    if entity_type == "vacuumValveRead":
        # record the port name of this entity
        read100Objects[entity.name] = entity.port

        entity.type = "dlsPLC.read100"
        entity.century = 0
        entity.remove("name")

    if entity_type == "vacuumValveRead2":
        # record the port name of this entity
        read100Objects[entity.name] = entity.port

        # TODO need an example to work out how to do this, we probably need
        # to record in read100Objects, which centry this entity is associated
        # WARNING: interlock.interlock will need to know about this (I think)
        raise NotImplementedError("vacuumValveRead2 not implemented")

    elif entity_type in ["vacuumValve", "vacuumValve_callback"]:
        entity.type = "dlsPLC.vacValve"

        entity.rename("crate", "vlvcc")
        entity.addr = int(entity.valve) * 10
        entity.remove("valve")

        entity.port = read100Objects[entity.vlvcc]

    elif entity_type == "vacuumValveGroup":
        entity.type = "dlsPLC.vacValveGroup"
        entity.remove("name")
