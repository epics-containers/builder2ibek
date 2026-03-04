from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "femto"

# Entity types where name has type: id (cross-referenced by other entities)
# These must keep their name parameter.
_id_name_types = {
    "femto200",
    "femto300",
    "femto100",
    "FluxCalcs",
    "simulation_femto",
}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    Strip name from leaf femto entities where name is just a GUI label
    (type: str), but preserve it for entities where name is type: id
    (cross-referenced by other entities).
    """
    if entity_type not in _id_name_types:
        entity.remove("name")
