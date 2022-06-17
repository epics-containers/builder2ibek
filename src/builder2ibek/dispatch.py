"""
Dispatch Builder XML elements to the appropriate handlers
"""

from builder2ibek.builder import Builder
from builder2ibek.convert import add_defaults, convert_generic
from builder2ibek.ioc import Generic_IOC
from builder2ibek.moduleinfos import module_infos


def dispatch(builder: Builder) -> Generic_IOC:
    """
    Use the correct convertor for each Builder XML module
    """
    ioc = Generic_IOC(builder.name, "auto-generated", "", [])

    for element in builder.elements:
        # default conversion to entity
        entity = convert_generic(element, ioc)

        if element.module in module_infos:
            info = module_infos[element.module]
            add_defaults(entity, info.defaults)
            info.handler(entity, entity["type"], ioc)

    return ioc
