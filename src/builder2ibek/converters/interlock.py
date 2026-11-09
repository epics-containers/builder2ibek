from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import hex_to_int

xml_component = "interlock"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the interlock support module

    This module gets converted to dlsPLC equivalents
    """

    if entity_type == "interlock":
        entity.type = "dlsPLC.interlock"
        entity.remove("name")
        hex_to_int(entity, "ilk")
        # interlock.interlock addr is a 10-word block number in the PLC DM
        # area (block nn = DM nn*10, zero-padded in the XML as "07");
        # dlsPLC.interlock addr is the first DM address of the interlock.
        if entity.addr is not None:
            entity.addr = int(entity.addr) * 10

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
        entity.remove("name")


def finalize(ioc: Generic_IOC):
    """
    Add the dlsPLC.read100 each dlsPLC.interlock depends on.

    dlsPLC.interlock reads its words from the $(device):DM<century>XX records
    of a dlsPLC.read100 for century addr//100. A read100 for that device and
    century may come from the XML (dlsPLC.read100, vacuumValveRead,
    temperaturePLCRead) anywhere in the IOC; add one only where none exists,
    just before the first interlock that needs it.

    The new read100 takes the interlock's port. dlsPLC.finalize repoints
    serial ports to their FINS .Hostlink port for both alike, whichever of
    the two finalizers runs first.
    """
    entities = ioc.entities

    present = {
        (e.get("device"), int(e["century"]))
        for e in entities
        if e.get("type") == "dlsPLC.read100" and e.get("century") is not None
    }

    i = 0
    while i < len(entities):
        e = entities[i]
        if e.get("type") == "dlsPLC.interlock" and e.get("addr") is not None:
            key = (e.get("device"), int(e["addr"]) // 100)
            if key not in present:
                present.add(key)
                read100 = {
                    "type": "dlsPLC.read100",
                    "century": key[1],
                    "device": key[0],
                }
                if e.get("port") is not None:
                    read100["port"] = e["port"]
                entities.insert(i, read100)
                i += 1
        i += 1
