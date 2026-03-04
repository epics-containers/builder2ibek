from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "zebra"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the zebra support module
    """

    if entity_type in ["zebra"]:
        # PREC is type: str in support YAML but xml2yaml converts "6" to int
        if "PREC" in entity:
            entity["PREC"] = str(entity["PREC"])
        # Q is optional with default "" - remove if empty to keep ioc.yaml clean
        if entity.get("Q") == "":
            entity.remove("Q")
