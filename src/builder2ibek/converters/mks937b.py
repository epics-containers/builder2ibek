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

    # mks937bGauge.id and mks937b.address are type: int in the support YAML,
    # but XML encodes them zero-padded ("02", "001") which the generic
    # converter preserves. Coerce to int; the support YAML re-pads with Jinja
    # (`{{ '%02d' % id }}`, `{{ '%03d' % address }}`) when rendering.
    if entity_type == "mks937bGauge" and entity.id is not None:
        entity.id = int(entity.id)
    if entity_type == "mks937b" and entity.address is not None:
        entity.address = int(entity.address)
