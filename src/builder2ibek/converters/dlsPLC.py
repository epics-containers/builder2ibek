from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "dlsPLC"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type == "fastVacuumChannel":
        # transform unit into quoted 2 digit format
        id_val = entity.get("id")
        id = int(id_val)  # type: ignore
        id_enum = f"{id:02d}"
        entity.id = id_enum

    # name is a gui association label, not cross-referenced by any entity
    # (except fastVacuumMaster, where name is used by fastVacuumChannel.master)
    if entity_type != "fastVacuumMaster":
        entity.remove("name")

    if entity_type == "flow":
        # address/bit params are type: str in support YAML but XML parses as int
        for field in ["loaddress", "lobit", "loloaddress", "lolobit"]:
            if hasattr(entity, field) and entity[field] is not None:
                entity[field] = str(entity[field])

    # remove blank interlock name fields
    new_entity = entity.copy()
    for key in entity.keys():
        if "ilk" in key and entity[key] == "":
            new_entity.pop(key)

    entity.clear()
    entity.update(new_entity)


def finalize(ioc: Generic_IOC):
    """
    Insert FINS.FINSHostlink port-layer entities for dlsPLC devices.

    dlsPLC device templates talk to the PLC through the FINS asyn driver
    (``@asyn($(port)...) FINS_DM_*``).  That requires ``port`` to be a FINS
    asyn port created by ``finsDEVInit``, not a bare serial port.  XMLbuilder
    referenced the serial port directly (the old vxWorks build used a
    StreamDevice Hostlink protocol instead), so for every serial port carrying
    dlsPLC devices we synthesise one FINS.FINSHostlink and repoint the dlsPLC
    entities at the ``.Hostlink`` port it creates.
    """
    entities: list[Entity] = ioc.entities  # type: ignore

    # names of all asyn serial ports declared in the IOC
    serial_ports = {
        e["name"]
        for e in entities
        if e.get("type") == "asyn.AsynSerial" and e.get("name")
    }

    # serial ports used by dlsPLC FINS devices, in first-seen order
    fins_ports: list[str] = []
    for e in entities:
        if str(e.get("type", "")).startswith("dlsPLC."):
            port = e.get("port")
            if port in serial_ports:
                if port not in fins_ports:
                    fins_ports.append(port)
                e["port"] = f"{port}.Hostlink"

    if not fins_ports:
        return

    # one FINSHostlink per serial port (keys ordered to match sorted output:
    # type first, then alphabetical)
    hostlinks = [
        Entity(type="FINS.FINSHostlink", asyn_port=port, name=f"{port}.Hostlink")
        for port in fins_ports
    ]

    # insert immediately after the last asyn.AsynSerial so the Hostlink pre_init
    # (HostlinkInterposeInit/finsDEVInit) runs after the serial port is created
    last_serial = max(
        i for i, e in enumerate(entities) if e.get("type") == "asyn.AsynSerial"
    )
    entities[last_serial + 1 : last_serial + 1] = hostlinks
