from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "utility"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the utility support module
    """

    # pingWait is handled by 'ibek do-wait' in epics-containers
    if entity_type == "pingWait":
        entity.delete_me()
        return

    # directoryWait waits, without end, for a directory on the builder IOC's
    # host, such as its autosave folder under /dls_sw. The container mounts
    # its own volumes (autosave at /autosave) before the IOC starts, and
    # those host paths do not exist in it.
    if entity_type == "directoryWait":
        entity.delete_me()
        return
