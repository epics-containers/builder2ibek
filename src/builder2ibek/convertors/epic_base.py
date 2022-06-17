from typing import Any, Dict

from builder2ibek.dataclasses import Generic_IOC

epics_base_defaults = {
    "EPICS_CA_MAX_ARRAY_BYTES": {
        "max_bytes": 6000000,
    }
}


def epics_base_handler(entity: Dict[str, Any], entity_type: str, ioc: Generic_IOC):

    if entity_type == "EpicsEnvSet":
        entity["max_bytes"] = entity["value"]
        del entity["key"], entity["value"]
        entity["key"] = "epics.EPICS_CA_MAX_ARRAY_BYTES"
