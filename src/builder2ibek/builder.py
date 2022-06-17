"""
Defines classes for reading a builder XML IOC definition
"""

from pathlib import Path
from typing import List
from xml.dom.minidom import parse

from builder2ibek.dataclasses import Element


class Builder:
    """
    A class for interpreting builder XML and creating a list of Element
    """

    def __init__(self) -> None:
        self.file: Path = Path()
        self.name: str = ""
        self.arch: str = ""
        self.elements: List[Element] = []

    def load(self, input_file: Path):
        """
        parse an XML file and populate this Builder object
        """
        self.file = input_file
        self.name = input_file.stem
        xml = parse(str(input_file))

        components = xml.firstChild
        assert components.tagName == "components"
        self.arch = components.attributes["arch"].nodeValue

        element = components.firstChild

        while element is not None:
            if element.attributes is not None:
                module_name, element_name = element.tagName.split(".", 1)
                attributes = {key: val for key, val in element.attributes.items()}

                new_element = Element(element_name, module_name, attributes)
                self.elements.append(new_element)

            element = element.nextSibling
