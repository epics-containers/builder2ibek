from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "devIocStats"

schema = ""


defaults = {
    "EPICS_CA_MAX_ARRAY_BYTES": {
        "max_bytes": 6000000,
    }
}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if (
        entity_type == "devIocStatsHelper" or entity_type == "iocAdminSoft"
        # TODO - to do the right thing here we need to know arch somehow
        # TODO but at present this is a Generic IOC target thing - not in the yaml
        # and ioc.arch == "linux-x86_64"
    ):
        print(f"removing {Entity}")
        entity.delete_me()
        return
        # in fact the above is nice because we by default add devIocStats.iocAdminSoft
        # using the env var IOC_NAME

        entity.type = f"{xml_component}.iocAdminSoft"
        if "ioc" in entity:
            entity.rename("ioc", "IOC")
        elif "name" in entity:
            entity.rename("name", "IOC")
        if "name" in entity:
            entity.remove("name")

        # we will always use the uppercase version of the instance YAML stem
        # for devIOCStats IOC name.
        entity.IOC = "{{ ioc_name | upper }}"
