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
    "https://github.com/epics-containers/ioc-pmac/releases/"
    "download/1.2.1/ioc.ibek.schema.yaml"
)

# A list of Tags and their default attributes
# These should match defaults supplied in builder.py __init__()
# NOTE: the build2ibek.support.py tool will now pick up the defaults
# from the builder.py __init__() function, so these are no longer needed
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
