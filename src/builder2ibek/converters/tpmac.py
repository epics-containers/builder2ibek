from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "tpmac"


def _lookup_pmac_prefix(entity, ioc):
    """Look up P prefix from pmacStatus entities matching this PMAC's port."""
    for check_entity in ioc.raw_entities:
        check_entity = Entity(**check_entity)
        if (
            "pmacStatus" in check_entity.type
            and check_entity.PORT == entity.pmacAsynPort
        ):
            entity.P = check_entity.DEVICE
            return


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the tpmac support module.

    Maps tpmac entities to their pmac equivalents.
    """

    if entity_type == "pmacAsynIPPort":
        entity.type = "pmac.pmacAsynIPPort"
    elif entity_type == "pmacDisableLimitsCheck":
        entity.type = "pmac.pmacDisableLimitsCheck"
    elif entity_type == "pmacVmeConfig":
        entity.type = "pmac.pmacVmeConfig"
    elif entity_type == "PMAC":
        entity.type = "pmac.PMAC"
        entity.rename("Port", "pmacAsynPort")
        _lookup_pmac_prefix(entity, ioc)
    elif entity_type == "GeoBrick":
        entity.type = "pmac.GeoBrick"
        entity.rename("Port", "pmacAsynPort")
        _lookup_pmac_prefix(entity, ioc)
