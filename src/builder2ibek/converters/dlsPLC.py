from builder2ibek.types import Entity, Generic_IOC

xml_component = "dlsPLC"


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type == "fastVacuumChannel":
        # transform unit into quoted 2 digit format
        id = int(entity.get("id"))
        id_enum = f"{id:02d}"
        entity.id = id_enum
