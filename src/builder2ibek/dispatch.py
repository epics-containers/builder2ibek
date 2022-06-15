"""
Dispatch Builder XML elements to the appropriate handlers
"""

from builder2ibek.builder import Builder
from builder2ibek.convert import Convert
from builder2ibek.ioc import Generic_IOC
from builder2ibek.moduleinfo import module_infos


def dispatch(builder: Builder) -> Generic_IOC:
    """
    Use the correct convertor for each Builder XML module
    """
    ioc = Generic_IOC(builder.name, "auto-generated", "", [])

    for element in builder.elements:
        if element.module in module_infos:
            info = module_infos[element.module]
            convertor = info.handler()
            convertor.convert(element, ioc)
        else:
            Convert.convert(element, ioc)

    return ioc
