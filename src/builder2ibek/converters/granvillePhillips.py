from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "granvillePhillips"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the granvillePhillips support
    module, which comes from its ibek-runtime-streamdevice pattern

    BL05I-VA-IOC-03, BL05J-VA-IOC-02 and BL06K-VA-IOC-01 are IOCs that use it.
    """

    # remove GUI only parameters, except on the controllers, whose name the
    # gauges' GCTLR refers to
    if entity_type not in ("gp350", "gp307"):
        entity.remove("name")

    # the builder took gctrl on the gauge readback templates but used it for
    # nothing, and their models do not declare it
    if entity_type in ("gp350Gauge", "gp307Gauge"):
        entity.remove("gctrl")
