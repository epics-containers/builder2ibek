import re

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "asyn"

vxSerial = re.compile(r"/ty/(\d\d)/(\d)")


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "AsynSerial":
        # check if this has a VxWorks serial device address
        m = vxSerial.match(entity.port)
        if m:
            # rename the device to the RTEMS scheme for serial port devices
            entity.port = f"/dev/tty{m.group(1)}{m.group(2)}"
