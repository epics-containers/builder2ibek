from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "CryoCoolerXV"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the CryoCoolerXV support module.
    Drops the builder object-identity 'name' from entities that don't use
    it as a db macro (CryocoolerLog, seqCsvLogger).
    """

    if entity_type in ["CryocoolerLog", "seqCsvLogger"]:
        entity.remove("name")
