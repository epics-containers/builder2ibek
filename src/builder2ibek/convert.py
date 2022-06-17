from typing import Any, Dict

from builder2ibek.builder import Element
from builder2ibek.ioc import Generic_IOC


def add_defaults(entity: Dict[str, Any], defaults: Dict[str, Dict[str, Any]]):
    this_entity_defaults = defaults.get(entity["type"])
    if this_entity_defaults:
        needed_defaults = {
            k: v for k, v in this_entity_defaults.items() if k not in entity
        }
        entity.update(needed_defaults)


def make_entity(element: Element) -> Dict[str, str]:
    """
    default Entity creation is a direct mapping
    of element name and attribute names/values to
    Entity type and argument names/values
    """

    entity = {}
    entity["type"] = f"{element.module}.{element.name}"

    for attribute_name, attribute_val in element.attributes.items():
        entity[attribute_name] = attribute_val

    return entity


def convert_generic(element: Element, ioc: Generic_IOC):
    entity = make_entity(element)
    ioc.entities.append(entity)
    return entity
