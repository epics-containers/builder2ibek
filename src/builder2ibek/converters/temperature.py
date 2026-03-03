from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "temperature"

# records {device, port} for each temperaturePLCRead, keyed by name
read100Objects: dict[str, dict[str, str]] = {}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the temperature support module

    temperaturePLCRead  → 2 dlsPLC.read100 (century=1 setpoints, century=2 readbacks)
    temperaturePLC      → dlsPLC.temperature
                          offset = addr*10 + indx
                          tmpcc/port looked up from the crate reference
    """

    if entity_type == "temperaturePLCRead":
        read100Objects[entity.name] = {
            "device": entity.device,
            "port": entity.port,
        }

        # Use plain dicts (not Entity()) to avoid resetting the class-level
        # _extra_entities list which Entity.__init__ clears on each instantiation.
        for century in [1, 2]:
            entity.add_entity(
                {
                    "type": "dlsPLC.read100",
                    "device": entity.device,
                    "port": entity.port,
                    "century": century,
                }
            )

        entity.delete_me()

    elif entity_type == "temperaturePLC":
        crate_info = read100Objects.get(entity.crate, {})
        entity.tmpcc = crate_info.get("device", "")
        entity.port = crate_info.get("port", "")
        entity.offset = int(entity.addr) * 10 + int(entity.indx)

        entity.remove("addr")
        entity.remove("indx")
        entity.remove("crate")

        entity.remove("name")
        entity.type = "dlsPLC.temperature"
