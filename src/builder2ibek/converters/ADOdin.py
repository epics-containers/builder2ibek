from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ADOdin"

# Entity types that are leaf nodes (not cross-referenced by other entities)
# and thus should have 'name' stripped
LEAF_ENTITIES = [
    "OdinLogConfig",
    "OdinBatchFile",
    "OdinStartAllScript",
    "OdinProcServ",
    "EigerOdinProcServ",
    "TristanControlSimulator",
]


def _find_raw_entity_by_name(ioc, name):
    """Find a raw entity by its 'name' attribute."""
    for raw in ioc.raw_entities:
        if raw.get("name") == name:
            return raw
    return None


def _resolve_control_server(ioc, server_name):
    """Look up control server entity and return (IP, PORT)."""
    raw = _find_raw_entity_by_name(ioc, server_name)
    if raw is None:
        return "", 8888
    ip = raw.get("IP", "")
    # Eiger uses CTRL_PORT, Tristan uses PORT
    port = raw.get("CTRL_PORT") or raw.get("PORT") or 8888
    return ip, int(port)


def _compute_total_processes(ioc, server_name):
    """Compute total OdinData processes across all data servers."""
    raw = _find_raw_entity_by_name(ioc, server_name)
    if raw is None:
        return 0
    total = 0
    for i in range(1, 11):
        ds_name = raw.get(f"ODIN_DATA_SERVER_{i}")
        if ds_name:
            ds_raw = _find_raw_entity_by_name(ioc, ds_name)
            if ds_raw:
                processes = ds_raw.get("PROCESSES")
                if processes:
                    total += int(processes)
    return total


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the ADOdin support module.

    - Strips 'name' from leaf entities
    - Resolves CONTROL_SERVER_IP, CONTROL_SERVER_PORT, and TOTAL
      for driver and detector entities from the referenced control server
    """

    # Strip 'name' from leaf entities
    if entity_type in LEAF_ENTITIES:
        entity.remove("name")

    # For EigerOdinDataDriver and TristanOdinDataDriver: resolve control server
    # IP/PORT and compute TOTAL OdinData processes
    if entity_type in ["EigerOdinDataDriver", "TristanOdinDataDriver"]:
        server_name = entity.get("ODIN_CONTROL_SERVER")
        if server_name:
            ip, port = _resolve_control_server(ioc, server_name)
            entity["CONTROL_SERVER_IP"] = ip
            entity["CONTROL_SERVER_PORT"] = port
            entity["TOTAL"] = _compute_total_processes(ioc, server_name)

    # For EigerDetector and TristanDetector: resolve control server IP/PORT
    if entity_type in ["EigerDetector", "TristanDetector"]:
        server_name = entity.get("ODIN_CONTROL_SERVER")
        if server_name:
            ip, port = _resolve_control_server(ioc, server_name)
            entity["CONTROL_SERVER_IP"] = ip
            entity["CONTROL_SERVER_PORT"] = port
