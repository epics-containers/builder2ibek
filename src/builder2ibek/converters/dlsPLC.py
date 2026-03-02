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

    # remove blank interlock name fields
    new_entity = entity.copy()
    for key in entity.keys():
        if "ilk" in key and entity[key] == "":
            new_entity.pop(key)

    entity.clear()
    entity.update(new_entity)
