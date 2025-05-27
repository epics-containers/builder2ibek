"""
Dataclasses for representing XML and YAML in memory
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Generic YAML classes #######################################################

DELETE_ME = "__delete_me__"


class Entity(dict[str, Any]):
    """
    Generic Entity has functions for using . notation which makes the code
    in the convertors package easier to type and read
    """

    _extra_entities: list["Entity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Entity._extra_entities = []

    def __getattr__(self, __name: str) -> Any:
        if __name in self:
            return self[__name]
        return None

    def __setattr__(self, __name: str, value) -> Any:
        self[__name] = value

    def remove(self, attr: str):
        if attr in self:
            del self[attr]

    def rename(self, attr: str, new: str):
        if attr in self:
            self[new] = self[attr]
            del self[attr]

    def add_entity(self, entity: "Entity"):
        self._extra_entities.append(entity)

    def get_extra_entities(self):
        return self._extra_entities

    def delete_me(self):
        self.__command__ = "delete"

    def is_deleted(self):
        return self.__command__ == "delete"


class Generic_IOC(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    ioc_name: str
    description: str
    entities: list[dict[str, Any]]
    raw_entities: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    source_file: Path


# Generic XML classes ##########################################################
@dataclass
class Element:
    name: str
    module: str
    attributes: dict[str, str]
