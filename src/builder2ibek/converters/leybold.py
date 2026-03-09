import re
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "leybold"

TEMPLATE_PATH = Path(
    "/dls_sw/prod/R3.14.12.7/support/leybold/2-2/etc/makeIocs/centerOne.xml"
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
    if entity_type == "centerOne":
        # Read the XML template
        xml_text = TEMPLATE_PATH.read_text()

        # Build substitution dict from entity attributes.
        attrs = dict(entity.items())
        attrs.pop("type", None)

        xml_text = _substitute_macros(xml_text, attrs)

        # Remove the entity and return expanded XML for re-dispatch
        return xml_text

    elif entity_type in (
        "center_one_gui",
        "read_string",
        "read_int",
        "read_floatE",
        "write_raw_int",
        "read_write_int",
        "read_int_floatE",
        "read_write_floatE_floatE",
        "read_float_float_float",
        "read_write_float",
    ):
        # Drop name from leaf entities (not cross-referenced)
        entity.remove("name")

        # All leybold parameters are passed as db macros (type: str).
        # Ensure any numeric-parsed YAML values are quoted strings.
        for key in list(entity.keys()):
            if key == "type":
                continue
            val = entity[key]
            if val is None:
                entity.remove(key)
            elif not isinstance(val, str):
                entity[key] = str(val)
