from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "mca"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the mca support module.
    """
    if entity_type == "sis3820":
        # sis3820 is an AsynPort — name is the port identifier used by
        # sub-entities (scaler32, SIS38XX_template, simple_mca_template).
        # Keep name and add an interrupt vector.
        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
    else:
        # All other mca entity types are leaf entities — strip name.
        entity.remove("name")
