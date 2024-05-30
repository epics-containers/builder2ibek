"""
Defines classes for reading a builder XML IOC definition
"""

from pathlib import Path
from xml.dom.minidom import Document, parse, parseString
from xml.dom.minidom import Element as DomElement

from builder2ibek.types import Element


class Builder:
    """
    A class for interpreting builder XML and creating a list of Element
    """

    def __init__(self) -> None:
        self.file: Path = Path()
        self.name: str = ""
        self.arch: str = ""
        self.elements: list[Element] = []

    def load_string(self, xml_str: str):
        """
        parse an XML string and populate this Builder object
        """
        self.file = Path("no_file")
        self.name = "no_name"
        xml = parseString(xml_str)
        self._parse(xml)

    def load(self, input_file: Path):
        """
        parse an XML file and populate this Builder object
        """
        self.file = input_file
        self.name = input_file.stem
        xml = parse(str(input_file))
        self._parse(xml)

    def _parse(self, xml: Document):
        components = xml.firstChild
        assert isinstance(components, DomElement)
        assert components.tagName == "components"
        self.arch = components.attributes["arch"].nodeValue

        element = components.firstChild

        while element is not None:
            if element.attributes is not None:  # type: ignore
                module_name, element_name = element.tagName.split(".", 1)  # type: ignore
                attributes = dict(element.attributes.items())  # type: ignore

                new_element = Element(element_name, module_name, attributes)
                self.elements.append(new_element)

            element = element.nextSibling
