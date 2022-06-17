from dataclasses import dataclass
from typing import Any, Callable, Dict

# MAINTENANCE: add imports for any new convertor functions here and then add a
# corresponding ModuleInfo to module_infos below
from builder2ibek.convertors.pmac import pmac_defaults, pmac_handler


@dataclass
class ModuleInfo:
    handler: Callable
    defaults: Dict[str, Dict[str, Any]]
    schema: str


url_pattern = "https://github.com/epics-containers/{}/releases/download/{}"

# MAINTENANCE: add any new convertor classes here
module_infos: Dict[str, ModuleInfo] = {
    "pmac": ModuleInfo(
        pmac_handler,
        pmac_defaults,
        url_pattern.format("ioc-pmac", "1.2.1/ioc.ibek.schema.yaml"),
    )
}
