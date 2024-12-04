from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL46P-BUILDER"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function
    """

    xml_dir = ioc.source_file.parent

    # probably should implement a generic way of handling builder xml templates
    # but for now just hard code the ones we know about for this specific module
    if entity_type == "BL4xP_EA1":
        name = "BL4xP-EA-IOC-01.xml"
    elif entity_type == "BL4xP_EA2":
        name = "BL4xP-EA-IOC-02.xml"
    elif entity_type == "BL4xP_MO1":
        name = "BL4xP-MO-IOC-01.xml"

    child_xml = xml_dir / name

    # returning new XML means throw away the old entity and make a new one
    new_xml = child_xml.read_text().replace("$(BL)", entity.BL)
    return new_xml
