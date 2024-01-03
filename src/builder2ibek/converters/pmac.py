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
        # remove GUI only parameters
        entity.remove("name")

    elif (
        entity_type == "dls_pmac_asyn_motor" or entity_type == "dls_pmac_cs_asyn_motor"
    ):
        if entity_type == "dls_pmac_cs_asyn_motor":
            entity.type = "pmac.dls_pmac_asyn_motor"
            entity.is_cs = True
        # standardise the name of the controller port
        entity.rename("PORT", "Controller")
        # this is calculated
        entity.remove("SPORT")
        # remove redundant parameters
        entity.remove("gda_desc")
        entity.remove("gda_name")
        # remove GUI only parameters
        entity.remove("name")
        # convert to enum
        if entity.DIR == 1:
            entity.DIR = "Neg"
        else:
            entity.DIR = "Pos"
        if entity.VMAX is not None:
            entity.VMAX = str(entity.VMAX)

    elif entity_type == "GeoBrick":
        entity.rename("Port", "pmacAsynPort")

    elif entity_type == "GeoBrickTrajectoryControlT":
        # don't bore the user with the fact this is a template!
        entity.type = "pmac.GeoBrickTrajectoryControl"
        # standardise the name of the controller port
        entity.rename("PORT", "PmacController")
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type == "autohome":
        # standardise the name of the controller port
        entity.rename("PORT", "PmacController")

    elif entity_type == "CS":
        # standardise the name of the controller port
        entity.rename("Controller", "PmacController")
        # this is calculated
        entity.remove("PARENTPORT")

    elif entity_type == "pmacVariableWrite":
        # remove GUI only parameters
        entity.remove("name")
        entity.remove("LABEL")

    elif entity_type == "pmacAsynIPPort":
        entity.remove("simulation")
