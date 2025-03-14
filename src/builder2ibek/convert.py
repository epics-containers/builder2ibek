"""
Generic XML to YAML conversion functions
"""

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, CommentedMap

from builder2ibek.builder import Builder, Element
from builder2ibek.moduleinfos import module_infos
from builder2ibek.types import Entity, Generic_IOC


def convert_file(xml: Path, yaml: Path, schema: str):
    def tidy_up(yaml):
        # add blank lines between major fields
        for field in [
            "ioc_name",
            "description",
            "entities",
            "  - type",
        ]:
            yaml = re.sub(rf"(\n{field})", "\n\\g<1>", yaml)
        return yaml

    """Convert a single builder XML file into a single ibek YAML"""
    builder = Builder()
    builder.load(xml)
    ioc = dispatch(builder, xml)

    ruamel = YAML()

    ruamel.default_flow_style = False
    # this attribute is for internal use, remove before serialising
    delattr(ioc, "source_file")
    yaml_map = CommentedMap(ioc.model_dump())

    # add support yaml schema
    yaml_map.yaml_add_eol_comment(f"yaml-language-server: $schema={schema}", column=0)

    ruamel.indent(mapping=2, sequence=4, offset=2)

    with yaml.open("w") as stream:
        ruamel.dump(yaml_map, stream, transform=tidy_up)


def dispatch(builder: Builder, filename) -> Generic_IOC:
    """
    Dispatch every element in the XML to the correct convertor
    and build a generic IOC from the converted Entities
    """
    ioc = Generic_IOC(
        ioc_name="{{  _global.get_env('IOC_NAME') }}",
        description="auto-generated by https://github.com/epics-containers/builder2ibek",
        # some default entities for all IOC instances
        entities=[
            {"type": "epics.EpicsEnvSet", "name": "EPICS_TS_MIN_WEST", "value": "0"},
            {
                "type": "epics.EpicsEnvSet",
                "name": "STREAM_PROTOCOL_PATH",
                "value": "/epics/runtime/protocol/",
            },
            {"type": "devIocStats.iocAdminSoft", "IOC": "{{ ioc_name | upper }}"},
        ],
        source_file=filename,
    )

    return do_dispatch(builder, ioc)


def do_dispatch(builder: Builder, ioc: Generic_IOC):
    for element in builder.elements:
        do_one_element(element, ioc)

    sorted_entities: list[Entity] = []
    for entity in ioc.entities:  # type: ignore
        # sort the args by key
        entity = Entity(sorted(entity.items()))  # type: ignore
        # but move type to the start of each entity
        entity = Entity(type=entity.pop("type"), **entity)
        sorted_entities.append(entity)

    ioc.entities = sorted_entities  # type: ignore
    return ioc


def do_one_element(element: Element, ioc: Generic_IOC):
    # first do default conversion to entity
    entity = convert_generic(element, ioc)

    # then dispatch to a specific handler if there is one
    assert isinstance(element, Element)

    if element.module in module_infos:
        info = module_infos[element.module]
    else:
        info = module_infos["generic"]
        info.yaml_component = element.module

    entity.type = f"{info.yaml_component}.{element.name}"
    new_xml = info.handler(entity, element.name, ioc)
    # if the handler added some new entities add them into the IOC
    extras = entity.get_extra_entities()
    if extras:
        for extra_entity in extras:
            ioc.entities.append(extra_entity)
        # move the new entity to after these extras at it is likely to depend on them
        ioc.entities.remove(entity)
        ioc.entities.append(entity)

    # if the handler returns a new XML string, parse it and dispatch the
    # new entities it defines to the correct handler
    if new_xml:
        new_builder = Builder()
        new_builder.load_string(new_xml)
        ioc.entities.remove(entity)
        do_dispatch(new_builder, ioc)
    if entity.is_deleted():
        ioc.entities.remove(entity)
    else:
        add_defaults(entity, info.defaults)


def add_defaults(entity: dict[str, Any], defaults: dict[str, dict[str, Any]]):
    this_entity_defaults = defaults.get(entity["type"])
    if this_entity_defaults:
        needed_defaults = {
            k: v for k, v in this_entity_defaults.items() if k not in entity
        }
        entity.update(needed_defaults)


def make_entity(element: Element) -> Entity:
    """
    default Entity creation is a direct mapping
    of element name and attribute names/values to
    Entity type and argument names/values
    """

    entity = Entity()
    entity.type = f"{element.module}.{element.name}"

    for attribute_name, attribute_val in element.attributes.items():
        # convert to numeric type if appropriate, otherwise Serialize will
        # put quotes around numbers in the YAML
        try:
            f = float(attribute_val)
            if f.is_integer():
                entity[attribute_name] = int(f)
            else:
                entity[attribute_name] = f
        except ValueError:
            entity[attribute_name] = attribute_val

    return entity


def convert_generic(element: Element, ioc: Generic_IOC) -> Entity:
    entity = make_entity(element)
    ioc.entities.append(entity)
    return entity
