from builder2ibek.types import Entity, Generic_IOC

xml_component = "pmac"

schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/"
    "download/1.2.1/ioc.ibek.schema.yaml"
)

defaults = {
    "pmac.GeoBrick": {
        "numAxes": 8,
        "idlePoll": 100,
        "movingPoll": 500,
    }
}


def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "pmacDisableLimitsCheck":
        entity.remove("name")

    elif entity_type == "dls_pmac_asyn_motor":
        # TODO unnecessary difference - could just call this dls_pmac_asyn_motor?
        entity.type = "pmac.DlsPmacAsynMotor"

        entity.rename("PORT", "Controller")
        entity.remove("SPORT")

    elif entity_type == "dls_pmac_cs_asyn_motor":
        # TODO unnecessary difference - could just call this DlsPmacAsynMotor?
        entity.type = "pmac.DlsPmacCsAsynMotor"

        entity.rename("PORT", "Controller")

    elif entity_type == "GeoBrick":
        # TODO unnecessary difference?
        entity.rename("Port", "PORT")

    elif entity_type == "CS":
        entity.remove("PARENTPORT")
