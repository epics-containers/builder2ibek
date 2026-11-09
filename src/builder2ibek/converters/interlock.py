import sys

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import hex_to_int, is_jinja, jinja_int

xml_component = "interlock"


def _scaled(addr, offset=None):
    """
    addr * 10 (+ offset): an int, or a Jinja expression for ibek to render
    when either is a cross-reference. Anything else that is not an integer
    raises.
    """
    if is_jinja(addr) or is_jinja(offset):
        expr = f"{jinja_int(addr)} * 10"
        if offset is not None:
            expr += f" + {jinja_int(offset)}"
        return f"{{{{ {expr} }}}}"
    return int(addr) * 10 + (0 if offset is None else int(offset))


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
        # A cross-referenced addr arrives as a Jinja string; scale it inside
        # the expression.
        if entity.addr is not None:
            entity.addr = _scaled(entity.addr)

    if entity_type == "overrideRequestMain":
        entity.type = "dlsPLC.overrideRequestMain"
        # https://confluence.diamond.ac.uk/x/i4kuAw#:~:text=addr%2C%20in%2C%20and,is%20outaddr%2D1
        entity.outaddr = _scaled(entity.addr, entity["in"])
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
    just before the first interlock that needs it. A century or addr given
    as a cross-reference (a Jinja string ibek renders) is not known here: a
    read100 with one is not counted, and an interlock with one gets a
    warning that its read100 must be supplied by hand.

    The new read100 takes the interlock's port. dlsPLC.finalize repoints
    serial ports to their FINS .Hostlink port for both alike, whichever of
    the two finalizers runs first.
    """
    entities = ioc.entities

    present = {
        (e.get("device"), int(e["century"]))
        for e in entities
        if e.get("type") == "dlsPLC.read100"
        and e.get("century") is not None
        and not is_jinja(e["century"])
    }

    i = 0
    while i < len(entities):
        e = entities[i]
        addr = e.get("addr")
        if e.get("type") != "dlsPLC.interlock" or addr is None:
            pass
        elif is_jinja(addr):
            print(
                f"warning: dlsPLC.interlock on {e.get('device')} has a "
                f"cross-referenced addr {addr!r}; add the dlsPLC.read100 for "
                "its century by hand",
                file=sys.stderr,
            )
        else:
            key = (e.get("device"), int(addr) // 100)
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
