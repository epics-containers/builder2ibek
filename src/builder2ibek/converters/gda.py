from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "gda"

REASON = (
    "the gda module's templates hold no records, only GDA tags for "
    "GDA's own configuration"
)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the gda support module

    builder2ibek won't convert gda: every entity type it defines (FE_motion,
    FE_vacuum, ID_gap, ID_phase and the rest) is left out with a warning.
    """
    ioc.wont_convert(entity, REASON)
