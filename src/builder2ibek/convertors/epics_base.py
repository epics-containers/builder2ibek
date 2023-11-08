from builder2ibek.types import Entity, Generic_IOC

xml_component = "EPICS_BASE"
yaml_component = "epics"


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "EpicsEnvSet" and entity["key"] == "EPICS_CA_MAX_ARRAY_BYTES":
        entity.rename("value", "max_bytes")
        entity.remove("key")
        entity.type = "epics.EpicsCaMaxArrayBytes"
    elif entity_type == "StartupCommand":
        if entity.post_init:
            entity.type = "epics.PostStartupCommand"
        else:
            entity.type = "epics.StartupCommand"
        entity.remove("post_init")