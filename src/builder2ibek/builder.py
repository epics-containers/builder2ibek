"""
Defines classes for reading a builder XML IOC definition
"""

from pathlib import Path
from typing import Dict, List
from xml.dom.minidom import parse

from .dispatch import dispatch


class Builder:
    def load(self, input_file: Path):
        """
        parse an XML file and build an ibek Support object model
        """
        entities: List[Dict[str, str]] = []
        xml = parse(str(input_file))

        components = xml.firstChild
        assert components.tagName == "components"
        arch = components.attributes["arch"].nodeValue

        element = components.firstChild

        while element is not None:
            if element.attributes is not None:
                builder_name = element.tagName
                attributes = {key: val for key, val in element.attributes.items()}

                entities.append(dispatch(arch, builder_name, attributes))

            element = element.nextSibling
