from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict

converters_path = Path(__file__).parent / "converters"


@dataclass
class ModuleInfo:
    handler: Callable
    defaults: Dict[str, Dict[str, Any]]
    schema: str
    yaml_component: str


module_infos: Dict[str, ModuleInfo] = {}


# automatically load all of the convert handlers in ./converters into the
# module_infos list using importlib
converters = converters_path.glob("*.py")
for converter in converters:
    if not converter.name.startswith("_"):
        module = import_module(f"builder2ibek.converters.{converter.stem}")
        if module is not None:
            xml_component = getattr(module, "xml_component")
            info = ModuleInfo(
                getattr(module, "handler", lambda *args: None),
                getattr(module, "defaults", {}),
                getattr(module, "schema", ""),
                getattr(module, "yaml_component", xml_component),
            )
            if isinstance(xml_component, str):
                module_infos[xml_component] = info

            elif isinstance(xml_component, list):
                for component in xml_component:
                    module_infos[component] = info
