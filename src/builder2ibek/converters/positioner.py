from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "positioner"

schema = ""

GDA_PLUGINS = Path(__file__).parent / "gdaPlugins.yaml"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "positioner":
        entity.DEADBAND = str(entity.DEADBAND)

    elif entity_type == "motorpositioner":
        # find the motor whose name = original motorpositioner.motor
        # the motor is of type "dls_pmac_asyn_motor" or "dls_pmac_cs_asyn_motor"
        # get the motor's PV and EGU
        # the motor's PV is claculated by concatenating its P and M params
        # set motorpositioner.motor = motor's PV
        # set motorpositioner.EGU = motor's PV
        motors = [
            e
            for e in ioc.raw_entities
            if e.get("type", "").endswith(
                ("dls_pmac_asyn_motor", "dls_pmac_cs_asyn_motor")
            )
            and e.get("name") == entity.motor
        ]
        assert len(motors) == 1
        motor = motors[0]
        motor_pv = motor["P"] + motor["M"]
        entity.motor = motor_pv
        entity.EGU = motor["EGU"]
