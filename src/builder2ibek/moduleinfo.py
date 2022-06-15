from dataclasses import dataclass
from typing import Dict, Type

# MAINTENANCE: add any new convertor functions here
from builder2ibek.convertors.pmac import Pmac


@dataclass
class ModuleInfo:
    handler: Type
    schema: str


url_pattern = "https://github.com/epics-containers/{}/releases/download/{}"

# MAINTENANCE: add any new convertor classes here
module_infos: Dict[str, ModuleInfo] = {
    "pmac": ModuleInfo(
        Pmac, url_pattern.format("ioc-pmac", "1.2.1/ioc.ibek.schema.yaml")
    )
}
