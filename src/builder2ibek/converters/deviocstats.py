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
    # convert.py injects devIocStats.iocAdminSoft as a default for every IOC,
    # so drop any devIocStats entry from the XML input.
    entity.delete_me()
