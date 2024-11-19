from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL20J"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module


    TODO we will NEVER support beamline specific support modules
    inside of GENERIC IOCs
    the example this was added for was BL20J-MO-IOC-02, see
    /dls_sw/work/R3.14.12.7/support/BL20J-BUILDER/etc/makeIocs/BL20J-MO-IOC-02.xml

    TODO above requires review and implementing differently.
    """
    entity.delete_me()
