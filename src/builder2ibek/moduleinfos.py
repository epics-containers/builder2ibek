from dataclasses import dataclass
from typing import Any, Callable, Dict

# MAINTENANCE: add imports for any new convertor functions here and then add a
# corresponding ModuleInfo to module_infos below
# todo this could be simplified using import lib and a function to make all the
# module_infos
from builder2ibek.convertors.epic_base import epics_base_defaults, epics_base_handler
from builder2ibek.convertors.pmac import pmac_defaults, pmac_handler


@dataclass
class ModuleInfo:
    handler: Callable
    defaults: Dict[str, Dict[str, Any]]


# MAINTENANCE: add any new convertor classes here
module_infos: Dict[str, ModuleInfo] = {
    "pmac": ModuleInfo(
        pmac_handler,
        pmac_defaults,
    ),
    "EPICS_BASE": ModuleInfo(
        epics_base_handler,
        epics_base_defaults,
    ),
}
