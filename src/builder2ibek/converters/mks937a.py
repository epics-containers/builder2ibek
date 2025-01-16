from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mks937a"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mks937a support module
    """
    # remove GUI only parameters (except on mks937aGauge which uses it for object ref)
    if entity_type not in ["mks937aGauge", "mks937a", "mks937aGaugeEGU"]:
        entity.remove("name")
