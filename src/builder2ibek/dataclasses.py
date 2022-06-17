"""
Dataclasses for representing XML and YAML in memory
"""
from dataclasses import dataclass
from typing import Any, Dict

# Generic YAML classes


@dataclass
class Generic_IOC:
    ioc_name: str
    description: str
    generic_ioc_image: str
    entities: list[Dict[str, Any]]


# Generic XML classes
@dataclass
class Element:
    name: str
    module: str
    attributes: Dict[str, str]
