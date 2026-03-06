from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL21I"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL21I support module
    """

    if entity_type in [
        "SCM10",
        "SMPLTempsController",
        "M5LimitLatch",
        "M5LimitStop",
        "M4ADCSupport",
        "ADCAcquisition",
        "ADCAcquisitionGroup",
        "DewarScales",
        "FS1Control",
        "FeedbackAutoPv",
        "S2DiodeDifference",
        "ARMAirControl",
        "AirBearingInterlockWait",
        "SGMTravellerAirControl",
        "SMPLValveSequence",
        "TTHBumpstripMonitor",
        "SMPLCollisionLimits",
    ]:
        entity.remove("name")

    if entity_type == "FS1Control":
        # Hyphens in param names break Jinja2 — rename to underscores
        entity.rename("RL-D_SWITCH", "RL_D_SWITCH")
        entity.rename("RL-C_SWITCH", "RL_C_SWITCH")
        entity.rename("RL-AB_SWITCH", "RL_AB_SWITCH")
