from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict

convertors_path = Path(__file__).parent / "convertors"


@dataclass
class ModuleInfo:
    handler: Callable
    defaults: Dict[str, Dict[str, Any]]
    schema: str
    yaml_component: str


module_infos: Dict[str, ModuleInfo] = {}


# automatically load all of the convert handlers in ./convertors into the
# module_infos list using importlib
convertors = convertors_path.glob("*.py")
for convertor in convertors:
    if not convertor.name.startswith("_"):
        module = import_module(f"builder2ibek.convertors.{convertor.stem}")
        if module is not None:
            xml_component = getattr(module, "xml_component")
            info = ModuleInfo(
                getattr(module, "handler", lambda *args: None),
                getattr(module, "defaults", {}),
                getattr(module, "schema", ""),
                getattr(module, "yaml_component", xml_component),
            )
            module_infos[xml_component] = info
