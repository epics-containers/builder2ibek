xml_component = "generic"


def handler(entity, entity_type, ioc, realHandler=None):
    """
    Generic/global entity handler
    """
    entity.remove("gda_name")
    entity.remove("gda_desc")

    # Convert special string values with known correct types
    for key, value in entity.items():
        if value == "False":
            entity[key] = False
        elif value == "True":
            entity[key] = True
        elif value == "":
            entity[key] = None

    if realHandler:
        return realHandler(entity, entity_type, ioc)
    else:
        return None


def globalHandler(realHandler):
    """
    Decorator for generic/global handler
    """
    return lambda entity, entity_type, ioc: handler(
        entity, entity_type, ioc, realHandler
    )
