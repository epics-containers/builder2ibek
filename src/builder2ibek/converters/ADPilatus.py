import re
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ADPilatus"

TEMPLATE_PATH = Path(
    "/dls_sw/prod/R3.14.12.7/support/ADPilatus/2-9dls4/etc/makeIocs/pilatusTemplate.xml"
)


def _substitute_macros(xml_text: str, attrs: dict) -> str:
    """Substitute $(MACRO) and $(MACRO=default) patterns with entity attributes."""

    def replacer(match):
        name = match.group(1)
        default = match.group(2)  # None if no default
        if name in attrs:
            return str(attrs[name])
        elif default is not None:
            return default
        else:
            return match.group(0)  # leave unsubstituted

    # Match $(NAME) and $(NAME=default)
    return re.sub(r"\$\((\w+?)(?:=([^)]*))?\)", replacer, xml_text)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "pilatusXmlTemplate":
        # Read the XML template
        xml_text = TEMPLATE_PATH.read_text()

        # Build substitution dict from entity attributes.
        # In the template, $(DETNAME) is used for object cross-references
        # (NDARRAY_PORT, port attributes). In ibek, PORT (type: id) serves
        # this role, so remap DETNAME to PORT value (PORTNAME.CAM).
        attrs = dict(entity.items())
        attrs.pop("type", None)

        # Map DETNAME to the PORT value so object references resolve correctly
        portname = attrs.get("PORTNAME", "")
        if portname:
            attrs["DETNAME"] = f"{portname}.CAM"

        xml_text = _substitute_macros(xml_text, attrs)

        # Remove the entity and return expanded XML for re-dispatch
        return xml_text

    elif entity_type == "pilatusDetector":
        entity.remove("name")
