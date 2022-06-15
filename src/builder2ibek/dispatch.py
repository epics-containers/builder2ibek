"""
Dispatch Builder XML elements to the appropriate handlers
"""
from ibek.ioc import IOC

from .builder import Builder


def dispatch(builder: Builder) -> IOC:
    """
    Choose the correct handler for each Builder XML element and return a
    Dictionary representing a ibek Entity
    """
    modules = builder.modules.keys()
    ioc = IOC(builder.name, "auto-generated", [], "")

    for module in modules:
        # TODO dispatch to the appropriate handler
        pass

    return ioc
