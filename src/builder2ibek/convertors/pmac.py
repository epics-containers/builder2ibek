from builder2ibek.builder import Element
from builder2ibek.convert import Convert
from builder2ibek.ioc import Generic_IOC


class Pmac(Convert):
    @classmethod
    def convert(cls, element: Element, ioc: Generic_IOC):

        ioc.entities.append(cls.make_entity(element))
