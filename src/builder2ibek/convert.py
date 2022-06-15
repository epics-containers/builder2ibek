from typing import Dict

from builder2ibek.builder import Element
from builder2ibek.ioc import Generic_IOC


class Convert:
    @classmethod
    def make_entity(cls, element: Element) -> Dict[str, str]:
        """
        default Entity creation is a direct mapping
        of element name and attribute names/values to
        Entity type and argument names/values
        """

        entity = {}
        entity["type"] = element.name

        for attribute_name, attribute_val in element.attributes.items():
            entity[attribute_name] = attribute_val

        return entity

    @classmethod
    def convert(cls, element: Element, ioc: Generic_IOC):
        ioc.entities.append(cls.make_entity(element))
