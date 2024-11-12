from builder2ibek.types import Entity, Generic_IOC

xml_component = "generic"

def handler(entity, entity_type, ioc, realHandler=None):
    """
    Default behavior: XML to YAML generic conversion module
    """
    entity.remove("gda_name")
    entity.remove("gda_desc")

    if realHandler:
        return realHandler(entity, entity_type, ioc)
    else:
        return None

def globalHandler(realHandler=None):
    """
    Decorator for generic global handler
    """
    return lambda entity, entity_type, ioc: handler(entity, entity_type, ioc, realHandler)