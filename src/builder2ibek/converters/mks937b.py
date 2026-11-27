from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC
from builder2ibek.utils import has_value

xml_component = "mks937b"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mks937b support module
    """

    # remove GUI only parameters (except entities whose name is cross-referenced:
    # mks937b via GCTLR, mks937bGauge/mks937bImg/mks937bPirg/mks937bCap/
    # auto_mks937bHcg via GAUGE; and auto_mks937bInterlock, whose records take
    # it as DESC)
    if entity_type not in (
        "mks937b",
        "mks937bGauge",
        "mks937bGaugeEGU",
        "mks937bImg",
        "mks937bPirg",
        "mks937bCap",
        "auto_mks937bHcg",
        "auto_mks937bInterlock",
    ):
        entity.remove("name")

    # mks937bGauge.id and mks937b.address are type: int in the support YAML,
    # but XML encodes them zero-padded ("02", "001") which the generic
    # converter preserves. Coerce to int; the support YAML re-pads with Jinja
    # (`{{ '%02d' % id }}`, `{{ '%03d' % address }}`) when rendering.
    if entity_type in ("mks937bGauge", "mks937bGaugeEGU") and has_value(entity.id):
        entity.id = int(entity.id)
    if entity_type == "mks937b" and has_value(entity.address):
        entity.address = int(entity.address)
