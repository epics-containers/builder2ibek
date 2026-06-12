from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "vacuumValve"

# records the port name and device prefix of each read100 entity, keyed by the
# builder object name (which the vacuumValve `crate` attribute references)
read100Objects: dict[str, dict[str, str]] = {}
# records devices already claimed by vacValve entities
vacValveDevices: set[str] = set()


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the vacuumValve support module

    This module gets converted to dlsPLC equivalents
    See https://confluence.diamond.ac.uk/x/i4kuAw
    """

    if entity_type == "vacuumValveRead":
        # record the port and device prefix of this entity
        read100Objects[entity.name] = {
            "port": entity.port,
            "device": entity.device,
        }

        entity.type = "dlsPLC.read100"
        entity.century = 0
        entity.remove("name")

    if entity_type == "vacuumValveRead2":
        # record the port and device prefix of this entity
        read100Objects[entity.name] = {
            "port": entity.port,
            "device": entity.device,
        }

        # TODO need an example to work out how to do this, we probably need
        # to record in read100Objects, which centry this entity is associated
        # WARNING: interlock.interlock will need to know about this (I think)
        raise NotImplementedError("vacuumValveRead2 not implemented")

    elif entity_type in ["vacuumValve", "vacuumValve_callback"]:
        entity.type = "dlsPLC.vacValve"

        entity.rename("crate", "vlvcc")
        entity.addr = int(entity.valve) * 10
        entity.remove("valve")
        entity.remove("name")

        # `crate` referenced the read100 by its builder object name; ibek's
        # `vlvcc` must instead be the read100 device prefix (e.g.
        # BL19I-VA-VLVCC-01) so the valve status links resolve to the real
        # :DMxXX records that read100 creates.
        read100 = read100Objects[entity.vlvcc]
        entity.port = read100["port"]
        entity.vlvcc = read100["device"]
        vacValveDevices.add(entity.device)

        # tclose_* fields came from builder but dlsPLC.vacValve does not support
        # them (a separate dlsPLC.vacValveTclose entity handles that).  Strip
        # them so validation passes.  The tclose template uses a different
        # addressing scheme (century/index) and is not yet implemented.
        for f in ["tclose_high", "tclose_hihi", "tclose_hhsv", "tclose_hsv"]:
            entity.remove(f)

    elif entity_type == "vacuumValveGroup":
        entity.type = "dlsPLC.vacValveGroup"
        entity.remove("name")

    elif entity_type == "auto_vacuumValveReadExtra":
        entity.type = "vacuumValve.vacuumValveReadExtra"
        entity.remove("name")

    elif entity_type == "externalValve":
        if entity.device in vacValveDevices:
            entity.delete_me()
        else:
            entity.type = "dlsPLC.externalValve"
            entity.remove("name")
