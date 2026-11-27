from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BLfeedback"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BLfeedback support module

    feedback is the BLfeedback pattern of ibek-runtime-support. beamPositionCalc
    calls beamPositionCalcConfigure, so it stays build-time, under the module
    name BLfeedbackCalc in ibek-support-dls.
    """
    if entity_type == "feedback":
        entity.remove("name")
    elif entity_type == "beamPositionCalc":
        entity.type = "BLfeedbackCalc.beamPositionCalc"
