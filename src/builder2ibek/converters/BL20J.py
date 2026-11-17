from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL20J"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL20J beamline module

    BL20J has no runtime pattern, so convert_file drops its entities from the
    ioc.yaml and lists them for manual review (see
    builder2ibek.patterns.drop_beamline_entities). BL20J-MO-IOC-02 is an IOC
    that uses it, see
    /dls_sw/work/R3.14.12.7/support/BL20J-BUILDER/etc/makeIocs/BL20J-MO-IOC-02.xml
    """
