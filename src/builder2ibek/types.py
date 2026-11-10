"""
Dataclasses for representing XML and YAML in memory
"""

from dataclasses import dataclass, field
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

    _extra_entities: list["Entity | dict[str, Any]"]

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

    def add_entity(self, entity: "Entity | dict[str, Any]"):
        self._extra_entities.append(entity)

    def get_extra_entities(self):
        return self._extra_entities

    def delete_me(self):
        self.__command__ = "delete"

    def is_deleted(self):
        return self.__command__ == "delete"


@dataclass
class WontConvert:
    """The entities of one type that an IOC drops, and why"""

    reason: str
    count: int = 0
    notes: list[str] = field(default_factory=list)


class Generic_IOC(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    ioc_name: str
    description: str
    entities: list[dict[str, Any]]
    raw_entities: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    source_file: Path
    # where the converted YAML is being written; extra files a convertor
    # generates go in side_files, which convert_file writes next to it
    out_dir: Path = Field(default=Path(), exclude=True)
    # emit BLGui.status / BLGui.device (xml2yaml --blgui); only for generic
    # IOCs whose binary includes the BLGui module
    blgui: bool = Field(default=False, exclude=True)
    already_converted: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    # entity types left out of the ioc.yaml on purpose, keyed by entity type
    wont_convert_types: dict[str, WontConvert] = Field(
        default_factory=dict, exclude=True
    )
    # files that go next to the ioc.yaml, by name; written only with it
    side_files: dict[str, str] = Field(default_factory=dict, exclude=True)
    # warnings that are not about a dropped entity type
    extra_warnings: list[str] = Field(default_factory=list, exclude=True)
    # the PandAs split out for fastcs-pandablocks (a fastcs_panda.PandaSplit)
    panda_split: Any = Field(default=None, exclude=True)

    def wont_convert(self, entity: Entity, reason: str, note: str = ""):
        """
        Leave an entity out of the ioc.yaml because builder2ibek won't convert
        it, and record a warning for the user. Warnings are grouped by entity
        type: one per type per IOC, carrying a count and any per-entity notes.
        """
        entity.delete_me()
        record = self.wont_convert_types.setdefault(
            str(entity.type), WontConvert(reason)
        )
        record.count += 1
        if note:
            record.notes.append(note)

    def warnings(self) -> list[str]:
        """One warning per entity type this IOC drops"""
        ioc = Path(self.source_file).stem
        lines = []
        for entity_type, record in self.wont_convert_types.items():
            plural = "entity" if record.count == 1 else "entities"
            text = (
                f"{ioc}: won't convert {record.count} {entity_type} {plural}, "
                f"left out of the ioc.yaml: {record.reason}"
            )
            lines.append("\n".join([text] + [f"  - {n}" for n in record.notes]))
        return lines + self.extra_warnings


# Generic XML classes ##########################################################
@dataclass
class Element:
    name: str
    module: str
    attributes: dict[str, str]
