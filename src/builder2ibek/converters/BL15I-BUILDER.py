from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL15I-BUILDER"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL15I-BUILDER module.

    BL15I-BUILDER is the I15 beamline's builder repo, which is never a runtime
    pattern: its templates are to be migrated into the BL15I beamline module.
    Until then convert_file drops each of its entities from the ioc.yaml and
    lists it for manual review (see builder2ibek.patterns.drop_beamline_entities).
    """
