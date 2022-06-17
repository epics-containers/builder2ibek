from builder2ibek.types import Entity, Generic_IOC

xml_component = "EPICS_BASE"

schema = ""


defaults = {
    "EPICS_CA_MAX_ARRAY_BYTES": {
        "max_bytes": 6000000,
    }
}


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):

    # TODO - we currently have a specific Entity type epics.EPICS_CA_MAX_ARRAY_BYTES
    # not sure this is wise and a general EPICS_BASE.EpicsEnvSet would be more
    # generally useful plus this would work with the generic conversion
    if entity_type == "EpicsEnvSet" and entity["key"] == "EPICS_CA_MAX_ARRAY_BYTES":
        entity.rename("value", "max_bytes")
        entity.remove("key")
        entity.type = "epics.EPICS_CA_MAX_ARRAY_BYTES"
