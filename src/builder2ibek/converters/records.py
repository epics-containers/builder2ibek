from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"

REASON = (
    "raw records have no entity model: recreate any that are still needed "
    "as a template in the IOC instance's config folder or in a support "
    "module (docs/how-to/after-beamline-convert.md, Custom templates)"
)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for raw records

    builder2ibek won't convert raw records: each one is left out, with one
    warning per record type naming the IOC and how many were dropped.
    """
    ioc.wont_convert(entity, REASON)
