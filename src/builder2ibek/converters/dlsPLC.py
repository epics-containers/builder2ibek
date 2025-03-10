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
    elif entity_type in [
        "NX102_readReal",
        "read100",
        "externalValve",
        "dummyValve",
        "overrideRequestMain",
        "vacValveGroup",
    ]:
        entity.remove("name")
    elif entity_type in ["vacValve", "vacValveDebounce"]:
        # name is not always present but is required by the auto-converted
        # dlsPLC.ibek.support.yaml - investigate why it is creating name=id
        # and fix the auto-conversion instead of having this workaround
        entity.name = entity.get("name") or entity.get("device")

    # remove blank interlock name fields
    new_entity = entity.copy()
    for key in entity.keys():
        if "ilk" in key and entity[key] == "":
            new_entity.pop(key)

    entity.clear()
    entity.update(new_entity)
