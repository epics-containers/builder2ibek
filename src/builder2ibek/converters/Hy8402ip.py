from builder2ibek.converters.epics_base import add_interrupt_vector
from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "Hy8402ip"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the Hy8402 support module
    """

    clockrate_map = {
        0: "1Hz",
        1: "2Hz",
        2: "5Hz",
        3: "10Hz",
        4: "20Hz",
        5: "50Hz",
        6: "100Hz",
        7: "200Hz",
        8: "500Hz",
        9: "1kHz",
        10: "2kHz",
        11: "5kHz",
        12: "10kHz",
        13: "20kHz",
        14: "50kHz",
        15: "100kHz",
    }

    if entity_type == "Hy8402":
        # Keep name - it is used for initHy8402ipAsyn port creation

        # Convert numeric clockRate to enum string
        if hasattr(entity, "clockRate") and entity.clockRate is not None:
            rate = int(entity.clockRate)
            if rate in clockrate_map:
                entity.clockRate = clockrate_map[rate]

        vec = add_interrupt_vector()
        entity.add_entity(vec)
        entity.interrupt_vector = vec.name
