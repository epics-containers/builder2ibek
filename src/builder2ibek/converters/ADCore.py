from xml.sax.saxutils import escape

from ruamel.yaml.scalarstring import LiteralScalarString

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.support_defaults import entity_params
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ADCore"

# escapes for an XML attribute value in double quotes, besides & < and >
_QUOTE = {'"': "&quot;"}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "NDPvaPlugin":
        entity.type = "ADCore.NDPvxsPlugin"

    elif entity_type == "NDAttributes":
        # one attribute in the NDAttributes XML of a driver or plugin port;
        # finalize writes each port's attributes into that port's entity
        attributes = entity.xml_attributes()
        port = attributes.get("port", "")
        ioc.nd_attributes.setdefault(port, []).append(nd_attribute(attributes))
        entity.delete_me()


def nd_attribute(xml: dict[str, str]) -> dict[str, str]:
    """
    The XML attributes of one <Attribute> element, made from the attributes
    of an ADCore.NDAttributes builder element as the ADCore builder.py
    NDAttributes class makes them, with its defaults
    """
    port = xml.get("port", "")
    source = xml.get("source", "")
    attr_type = xml.get("type") or "EPICS_PV"
    attribute = {
        "name": xml.get("attrname") or f"{port}.{source}",
        "type": attr_type,
        "source": source,
        "description": xml.get("description", ""),
    }
    if attr_type == "EPICS_PV":
        attribute["dbrtype"] = xml.get("dbrtype") or "DBR_NATIVE"
    else:
        attribute["datatype"] = xml.get("datatype") or "INT"
        attribute["addr"] = xml.get("addr") or "0"
    return attribute


def attributes_xml(attributes: list[dict[str, str]]) -> str:
    """
    The NDAttributes XML for a list of attributes, one <Attribute> element a
    line, with its XML attributes in name order as XMLbuilder wrote them
    """
    lines = ["<Attributes>"]
    for attribute in attributes:
        fields = " ".join(
            f'{k}="{escape(v, _QUOTE)}"' for k, v in sorted(attribute.items())
        )
        lines.append(f"  <Attribute {fields}/>")
    lines.append("</Attributes>")
    return "\n".join(lines) + "\n"


def finalize(ioc: Generic_IOC):
    """
    Give each port that ADCore.NDAttributes elements attach to its
    NDAttributes XML.

    XMLbuilder wrote the XML to a file per port and set the port's
    NDAttributesFile to it. Here it goes inline in the ATTRIBUTES_FILE of the
    port's driver or plugin entity. An entity model without ATTRIBUTES_FILE
    gets the XML as a file next to the ioc.yaml instead, set by an
    ADCore.NDAttributesConfig entity: inline XML would not fit the
    NDAttributesFile record, whose size only those models can grow.
    """
    # convert imports every converter, this one included
    from builder2ibek.convert import ordered_params

    entities: list[Entity] = ioc.entities  # type: ignore
    ioc_name = ioc.source_file.stem if ioc.source_file else ""

    for port, attributes in ioc.nd_attributes.items():
        xml = attributes_xml(attributes)
        count = f"{len(attributes)} ADCore.NDAttributes"

        # make_entity turns a numeric-looking PORT into a number
        target = next((e for e in entities if str(e.get("PORT")) == port), None)
        if target is None:
            ioc.extra_warnings.append(
                f"{ioc_name}: dropped {count} for port {port}: no converted "
                "driver or plugin has that PORT"
            )
            continue

        params = entity_params(str(target["type"]))
        if params is not None and "ATTRIBUTES_FILE" in params:
            target["ATTRIBUTES_FILE"] = LiteralScalarString(xml)
            _reorder(target, ordered_params(target))
            continue

        if "P" not in target or "R" not in target:
            ioc.extra_warnings.append(
                f"{ioc_name}: dropped {count} for port {port}: its entity "
                f"{target['type']} has no ATTRIBUTES_FILE, P or R"
            )
            continue

        file_name = f"{port}.xml"
        ioc.side_files[file_name] = '<?xml version="1.0" ?>\n' + xml
        config = ordered_params(
            {
                "type": "ADCore.NDAttributesConfig",
                "P": target["P"],
                "R": target["R"],
                "ATTRIBUTES_FILE": file_name,
            }
        )
        entities.insert(entities.index(target) + 1, config)  # type: ignore
        reason = (
            "has no ATTRIBUTES_FILE"
            if params is not None
            else "has no entity model in ibek-support or ibek-support-dls"
        )
        ioc.extra_warnings.append(
            f"{ioc_name}: {target['type']} {reason}, so the NDAttributes XML "
            f"for port {port} goes in {file_name} next to the ioc.yaml, set by "
            "an ADCore.NDAttributesConfig entity"
        )


def _reorder(entity: dict, ordered: dict):
    """Put an entity's keys in place in the given order"""
    entity.clear()
    entity.update(ordered)
