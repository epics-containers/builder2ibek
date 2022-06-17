from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict

convertors_path = Path(__file__).parent / "convertors"


@dataclass
class ModuleInfo:
    handler: Callable
    defaults: Dict[str, Dict[str, Any]]


module_infos: Dict[str, ModuleInfo] = {}


# automatically load all of the convert handlers in ./convertors into the
# module_infos list using importlib
# All modules in package convertors need to implement 'handler' and provide
# 'schema' and 'defaults'
convertors = convertors_path.glob("*.py")
for convertor in convertors:
    if not convertor.name.startswith("_"):
        module = import_module(f"builder2ibek.convertors.{convertor.stem}")
        if module is not None:
            info = ModuleInfo(getattr(module, "handler"), getattr(module, "defaults"))
            module_infos[convertor.stem] = info
