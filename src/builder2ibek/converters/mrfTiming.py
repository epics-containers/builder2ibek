from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mrfTiming"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """

    # TODO mrfTiming not yet implemented - does it really need a irq
    if entity_type == "EventReceiverPMC":
        vec = add_interrupt_vector()
        entity.add_entity(vec)
