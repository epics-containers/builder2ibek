"""
Dataclasses for representing XML and YAML in memory
"""
from dataclasses import dataclass
from typing import Any, Dict

# Generic YAML classes #########################################################


@dataclass
class Generic_IOC:
    ioc_name: str
    # TODO arch is not in ibek's IOC class but probably should be
    arch: str
    description: str
    generic_ioc_image: str
    entities: list[Dict[str, Any]]


class Entity(Dict[str, Any]):
    """
    Generic Entity has functions for using . notation which makes the code
    in the convertors package easier to type and read
    """

    def __getattr__(self, __name: str) -> Any:
        return self[__name]

    def __setattr__(self, __name: str, value) -> Any:
        self[__name] = value

    def remove(self, attr: str):
        del self[attr]

    def rename(self, attr: str, new: str):
        self[new] = self[attr]
        del self[attr]


# Generic XML classes ##########################################################


@dataclass
class Element:
    name: str
    module: str
    attributes: Dict[str, str]
