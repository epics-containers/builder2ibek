"""
Defines classes for reading a builder XML IOC definition
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from xml.dom.minidom import parse


@dataclass
class Element:
    name: str
    attributes: Dict[str, str]


@dataclass
class Module:
    name: str
    elements: List[Element]


class Builder:
    """
    A class for interpreting builder XML and creating an object graph of its
    contents like this:
    Builder -> Dictionary of Module -> List of Element -> Element name, Attributes
    """

    def __init__(self) -> None:
        file: str
        name: str
        arch: str
        modules: Dict[str, Module]

    def load(self, input_file: Path):
        """
        parse an XML file and populate this Builder object
        """
        self.file = input_file
        self.name = input_file.stem
        self.modules: Dict[str, Module] = {}
        xml = parse(str(input_file))

        components = xml.firstChild
        assert components.tagName == "components"
        self.arch = components.attributes["arch"].nodeValue

        element = components.firstChild

        while element is not None:
            if element.attributes is not None:
                module_name, element_name = element.tagName.split(".", 1)
                attributes = element.attributes.items()

                if module_name not in self.modules:
                    self.modules[module_name] = Module(module_name, [])

                self.modules[module_name].elements.append(
                    Element(element_name, attributes)
                )

            element = element.nextSibling
