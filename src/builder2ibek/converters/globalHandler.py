xml_component = "generic"


def handler(entity, entity_type, ioc, realHandler=None):
    """
    Generic/global entity handler
    """
    entity.remove("gda_name")
    entity.remove("gda_desc")
    entity.remove("gda_curr_name")

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
        # Entities reaching the generic fallback are leaf entities with no
        # specific converter — strip name since it cannot be cross-referenced.
        entity.remove("name")
        return None


def globalHandler(realHandler):
    """
    Decorator for generic/global handler
    """
    return lambda entity, entity_type, ioc: handler(
        entity, entity_type, ioc, realHandler
    )
