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
    if entity.type == "pmacDisableLimitsCheck":
        entity.remove("name")
    elif entity.type == "pmac.DlsPmacAsynMotor":
        # TODO unnecessary difference - could just call this DlsPmacAsynMotor?
        entity.type = "pmac.dls_pmac_asyn_motor"
        entity.rename("PORT", "Controller")
        entity.remove("SPORT")
