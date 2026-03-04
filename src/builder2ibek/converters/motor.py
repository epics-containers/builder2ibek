from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motor"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the motor support module.

    basic_asyn_motor has name: type: id (cross-referenced by other entities),
    so name must be preserved. Other motor entity types that are leaf entities
    can have name stripped.
    """
    if entity_type == "basic_asyn_motor":
        # Coerce numeric-looking str params to str
        for field in ("VMAX", "BACC", "DHLM", "DLLM", "JAR", "ERES", "RDBD"):
            val = entity.get(field)
            if val is not None and not isinstance(val, str):
                entity[field] = str(val)

    if entity_type.startswith("auto_"):
        entity.remove("name")
