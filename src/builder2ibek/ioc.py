from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Generic_IOC:
    ioc_name: str
    description: str
    generic_ioc_image: str
    entities: list[Dict[str, Any]]
