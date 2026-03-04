from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mks937b"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mks937b support module
    """

    # remove GUI only parameters (except entities whose name is cross-referenced:
    # mks937b via GCTLR, mks937bGauge/mks937bImg/mks937bPirg/mks937bCap via GAUGE)
    if entity_type not in (
        "mks937b",
        "mks937bGauge",
        "mks937bImg",
        "mks937bPirg",
        "mks937bCap",
    ):
        entity.remove("name")
