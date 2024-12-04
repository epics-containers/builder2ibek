"""
The convertor handler module for pmac support module
"""

from builder2ibek.converters.globalHandler import globalHandler
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


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    # remove redundant parameters
    entity.remove("gda_desc")
    entity.remove("gda_name")

    if entity_type == "pmacDisableLimitsCheck":
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type in [
        "dls_pmac_asyn_motor",
        "dls_pmac_cs_asyn_motor",
    ]:
        if entity_type == "dls_pmac_cs_asyn_motor":
            entity.type = "pmac.dls_pmac_asyn_motor"
            entity.is_cs = True
        # standardise the name of the controller port
        entity.rename("PORT", "Controller")
        # this is calculated
        entity.remove("SPORT")
        # remove GUI only parameters
        entity.remove("name")
        # convert to enum
        if entity.DIR == 1:
            entity.DIR = "Neg"
        else:
            entity.DIR = "Pos"
        if entity.VMAX is not None:
            entity.VMAX = str(entity.VMAX)
        # convert to enum
        if entity.UEIP == 1:
            entity.UEIP = "Yes"
        else:
            entity.UEIP = "No"
        if entity.FOFF == 1:
            entity.FOFF = "Frozen"
        else:
            entity.FOFF = "Variable"

    elif entity_type == "auto_translated_motor":
        # remove GUI only parameters
        entity.remove("name")
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
        # remove GUI only parameters
        entity.remove("name")
        # standardise the name of the controller port
        entity.rename("PORT", "PmacController")

    elif entity_type in ["pmacCreateCsGroup", "pmacCsGroupAddAxis"]:
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type == "CS":
        # standardise the name of the controller port
        entity.rename("Controller", "PmacController")
        # this is calculated
        entity.remove("PARENTPORT")
        # this is a redundant parameter
        entity.remove("PLCNum")

    elif entity_type == "pmacVariableWrite":
        # remove GUI only parameters
        entity.remove("name")
        entity.remove("LABEL")

    elif entity_type == "pmacAsynIPPort":
        entity.remove("simulation")
        if ":" not in entity.IP:
            entity.IP = entity.IP + ":1025"
