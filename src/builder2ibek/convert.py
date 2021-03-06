"""
Generic XML to YAML conversion functions
"""
from typing import Any, Dict

from builder2ibek.builder import Builder, Element
from builder2ibek.moduleinfos import module_infos
from builder2ibek.types import Entity, Generic_IOC


def dispatch(builder: Builder) -> Generic_IOC:
    """
    Dispatch every element in the XML to the correct convertor
    and build a generic IOC from the converted Entities
    """
    ioc = Generic_IOC(builder.name.lower(), builder.arch, "auto-generated", "", [])

    for element in builder.elements:
        # first do default conversion to entity
        entity = convert_generic(element, ioc)

        # then dispatch to a specific handler if there is one
        if element.module in module_infos:
            info = module_infos[element.module]
            info.handler(entity, element.name, ioc)
            add_defaults(entity, info.defaults)

    return ioc


def add_defaults(entity: Dict[str, Any], defaults: Dict[str, Dict[str, Any]]):
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
    entity["type"] = f"{element.module}.{element.name}"

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
