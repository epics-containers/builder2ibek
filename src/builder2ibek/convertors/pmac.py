"""
The convertor handler module for pmac support module
"""

from builder2ibek.types import Entity, Generic_IOC

# The prefix for Builder XML Tags that this support module uses
xml_component = "pmac"

# The ibek schema for the Generic IOC that compiles this support module
# (currently not used) TODO it would be good to pull in the schema and
# verify that the YAML we generate is valid against it.
schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/download/"
    "2023.11.1/ibek.ioc.schema.json"
)


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type == "pmacDisableLimitsCheck":
        entity.remove("name")

    elif (
        entity_type == "dls_pmac_asyn_motor" or entity_type == "dls_cs_pmac_asyn_motor"
    ):
        entity.rename("PORT", "Controller")
        entity.remove("SPORT")
        entity.remove("gda_desc")
        entity.remove("gda_name")
        if entity.DIR == 1:
            entity.DIR = "Neg"
        else:
            entity.DIR = "Pos"
        if entity.VMAX is not None:
            entity.VMAX = str(entity.VMAX)

    elif entity_type == "GeoBrickTrajectoryControlT":
        entity.type = "pmac.GeoBrickTrajectoryControl"
        entity.remove("name")
        entity.rename("PORT", "PmacController")

    elif entity_type == "autohome":
        entity.rename("PORT", "PmacController")
