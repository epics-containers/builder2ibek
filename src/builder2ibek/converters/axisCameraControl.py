import re

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "axisCameraControl"

# etc/makeIocs/axisCamera.xml of axisCameraControl 2-1 to 2-4, which the builder
# class axisCamera (an iocbuilder Xml) instantiates with its own arguments
AXIS_CAMERA_XML = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
	<EPICS_BASE.EpicsEnvSet key="EPICS_CA_MAX_ARRAY_BYTES" name="arraySize" value="10000000"/>
	<ADURL.URLDriver ADDR="0" P="$(P)" PORT="$(name)" R=":CAM:" TIMEOUT="5" BUFFERS="$(BUFFERS=50)"/>
	<asyn.AsynIP name="$(name).control" port="$(IPADDR):80 http"/>
	<axisCameraControl.axisCameraControl P="$(P):CONTROL" PORT="$(name).control" name="$(name).control"/>
	<EPICS_BASE.dbpf name="$(name).URL1" pv="$(P):CAM:URL1" value="http://$(IPADDR)/axis-cgi/jpg/image.cgi"/>
	<EPICS_BASE.dbpf name="$(name).URL2" pv="$(P):CAM:URL2" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL3" pv="$(P):CAM:URL3" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL4" pv="$(P):CAM:URL4" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL5" pv="$(P):CAM:URL5" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL6" pv="$(P):CAM:URL6" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL7" pv="$(P):CAM:URL7" value=""/>
	<EPICS_BASE.dbpf name="$(name).URL8" pv="$(P):CAM:URL8" value=""/>
	<EPICS_BASE.dbpf name="$(name).NAME1" pv="$(P):CAM:URLSelect.ZRST" value="Axis Camera"/>
	<EPICS_BASE.dbpf name="$(name).NAME2" pv="$(P):CAM:URLSelect.ONST" value="Spare 1"/>
	<EPICS_BASE.dbpf name="$(name).NAME3" pv="$(P):CAM:URLSelect.TWST" value="Spare 2"/>
	<EPICS_BASE.dbpf name="$(name).NAME4" pv="$(P):CAM:URLSelect.THST" value="Spare 3"/>
	<EPICS_BASE.dbpf name="$(name).NAME5" pv="$(P):CAM:URLSelect.FRST" value="Spare 4"/>
	<EPICS_BASE.dbpf name="$(name).NAME6" pv="$(P):CAM:URLSelect.FVST" value="Spare 5"/>
	<EPICS_BASE.dbpf name="$(name).NAME7" pv="$(P):CAM:URLSelect.SXST" value="Spare 6"/>
	<EPICS_BASE.dbpf name="$(name).NAME8" pv="$(P):CAM:URLSelect.SVST" value="Spare 7"/>
	<EPICS_BASE.dbpf name="$(name).SEL" pv="$(P):CAM:URLSelect" value="0"/>
</components>
"""  # noqa: E501


def _substitute_macros(xml_text: str, attrs: dict) -> str:
    """Substitute $(MACRO) and $(MACRO=default) with the entity's arguments."""

    def replacer(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        if name in attrs:
            return str(attrs[name])
        return default if default is not None else match.group(0)

    return re.sub(r"\$\((\w+?)(?:=([^)]*))?\)", replacer, xml_text)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the axisCameraControl module
    """
    if entity_type == "axisCamera":
        attrs = {k: v for k, v in entity.items() if k != "type"}
        # the entity is replaced by the components of axisCamera.xml
        return _substitute_macros(AXIS_CAMERA_XML, attrs)

    # no axisCameraControl entity is referred to by another
    entity.remove("name")
