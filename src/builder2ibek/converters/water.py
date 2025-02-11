from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "water"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the water support module

    This module gets converted to dlsPLC equivalents
    """

    # water.flow and dlsPLC.flow do not appear to be equivalent
    # I believe there is no dlsPLC for this;
    # https://confluence.diamond.ac.uk/display/CNTRLS/Upgrade+a+Vacuum+IOC+to+use+dlsPLC#:~:text=This%20template%20reads,need%20to%20change.
    # if entity_type == "flow":
    #     entity.type = "dlsPLC.flow"
    #     entity.remove("name")
