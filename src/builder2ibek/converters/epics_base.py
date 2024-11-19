from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "EPICS_BASE"
yaml_component = "epics"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "EpicsEnvSet":
        if entity["key"] == "EPICS_CA_MAX_ARRAY_BYTES":
            entity.rename("value", "max_bytes")
            entity.remove("key")
            entity.remove("name")
            entity.type = "epics.EpicsCaMaxArrayBytes"
        else:
            entity.rename("key", "name")
            # remove IOCSH settings as epics-containers makes the iocsh prompt
            if "IOCSH" in entity.name:
                entity.delete_me()
    elif entity_type == "StartupCommand":
        if entity.post_init:
            entity.type = "epics.PostStartupCommand"
        else:
            entity.type = "epics.StartupCommand"
        entity.remove("post_init")

    elif entity_type == "dbpf":
        entity.type = "epics.Dbpf"
        entity.value = str({entity.value})
