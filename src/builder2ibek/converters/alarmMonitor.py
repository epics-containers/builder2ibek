from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "alarmMonitor"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the alarmMonitor support module
    """
    # name is a GUI label: no entity refers to an alarmMonitor
    entity.remove("name")

    # str params that XML parses as numbers, e.g. INPB="1e-03": keep the text.
    # Every param is str except alarmNoAck's DISABLEVAL
    xml = entity.xml_attributes()
    str_fields = ("P", "R", "INPA", "INPB", "CONDITION", "ALARMSTAT", "DISABLELINK")
    for field in str_fields:
        val = entity.get(field)
        if val is not None and not isinstance(val, str):
            entity[field] = xml.get(field, str(val))
