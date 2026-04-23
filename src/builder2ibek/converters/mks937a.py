from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mks937a"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the mks937a support module
    """
    # remove GUI only parameters (except on mks937aGauge which uses it for object ref)
    if entity_type not in ["mks937aGauge", "mks937a"]:
        entity.remove("name")

    # mks937aGauge(EGU).id is type: int in the support YAML, but XML encodes
    # it as a zero-padded string (e.g. "02") which the generic converter
    # preserves. Coerce to int so ioc.yaml holds a bare integer; the support
    # YAML re-pads with Jinja (`{{ '%02d' % id }}`) when rendering databases.
    if entity_type in ("mks937aGauge", "mks937aGaugeEGU") and entity.id is not None:
        entity.id = int(entity.id)
