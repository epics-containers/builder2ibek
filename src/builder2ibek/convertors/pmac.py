"""
The convertor handler module for pmac support module
"""

from builder2ibek.types import Entity, Generic_IOC

# The prefix for Builder XML Tags that this support module uses
xml_component = "pmac"

# The ibek schema for the Generic IOC that compiles this support module
# (currently not used)
schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/"
    "download/1.2.1/ioc.ibek.schema.yaml"
)

# A list of Tags and their default attributes
# These should match defaults supplied in builder.py __init__()
defaults = {
    "pmac.GeoBrick": {
        "numAxes": 8,
        "idlePoll": 100,
        "movingPoll": 500,
    }
}


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    if entity_type == "pmacDisableLimitsCheck":
        entity.remove("name")

    elif entity_type == "dls_pmac_asyn_motor":
        # TODO unnecessary difference -
        # could just call this dls_pmac_asyn_motor in ibek definition ?
        entity.type = "pmac.DlsPmacAsynMotor"

        entity.rename("PORT", "Controller")
        entity.remove("SPORT")

    elif entity_type == "dls_pmac_cs_asyn_motor":
        # TODO unnecessary difference
        entity.type = "pmac.DlsPmacCsAsynMotor"

        entity.rename("PORT", "Controller")

    elif entity_type == "GeoBrick":
        # TODO unnecessary difference?
        entity.rename("Port", "PORT")

    elif entity_type == "CS":
        entity.remove("PARENTPORT")
