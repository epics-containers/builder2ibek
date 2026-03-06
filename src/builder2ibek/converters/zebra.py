from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "zebra"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the zebra support module
    """

    if entity_type in ["zebra"]:
        # These params are type: str in support YAML but xml2yaml may emit bare ints
        for key in [
            "PREC",
            "M1MULT",
            "M2MULT",
            "M3MULT",
            "M4MULT",
            "M1HOMESETTLE",
            "M2HOMESETTLE",
            "M3HOMESETTLE",
            "M4HOMESETTLE",
        ]:
            if key in entity and not isinstance(entity[key], str):
                entity[key] = str(entity[key])
        # Q is optional with default "" - remove if empty to keep ioc.yaml clean
        if entity.get("Q") == "":
            entity.remove("Q")
