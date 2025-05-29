"""
The convertor handler module for pmacUtil support module.
This converts things to pmac rather than pmacUtil.
"""

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.converters.pmac import handler as pmacHandler
from builder2ibek.types import Entity, Generic_IOC

# The prefix for Builder XML Tags that this support module uses
xml_component = "pmacUtil"

# The ibek schema for the Generic IOC that compiles this support module
# (currently not used) TODO it would be good to pull in the schema and
# verify that the YAML we generate is valid against it.
schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/download/"
    "2023.11.1/ibek.ioc.schema.json"
)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmacUtil support module
    """

    entity.type = entity.type.replace("pmacUtil", "pmac")
    # this is calculated
    entity.remove("PMAC")
    if entity_type == "pmacStatus":
        entity.delete_me()
    elif entity_type == "autohome":
        for check_entity in ioc.raw_entities:
            check_entity = Entity(**check_entity)
            if check_entity.type.endswith("GeoBrick"):
                if check_entity.Port == entity.PORT:
                    entity.PORT = check_entity.name

    # conversions are identical to pmac from this point
    pmacHandler(entity, entity_type, ioc)
