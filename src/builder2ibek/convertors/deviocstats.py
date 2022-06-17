from builder2ibek.types import Entity, Generic_IOC

xml_component = "devIocStats"

schema = ""


defaults = {
    "EPICS_CA_MAX_ARRAY_BYTES": {
        "max_bytes": 6000000,
    }
}


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):

    if entity_type == "devIocStatsHelper" and ioc.arch == "linux-x86_64":
        entity.type = f"{xml_component}.iocAdminSoft"
        entity.rename("ioc", "IOC")
        entity.remove("name")
