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

    # Don't remove multipositioner's name because motorpostioner references it
    elif entity_type == "positioner":
        entity.remove("name")

    elif entity_type == "motorpositioner":
        entity.remove("name")

        # Find the dls_pmac_asyn_motor whose name = original motorpositioner.motor.
        # There is also dls_pmac_cs_asyn_motor but I don't need it for B21 IOCs,
        # so leave it out of the search for now.
        # Get the motor's PV and EGU, the motor's PV is calculated by concatenating
        # its P and M params.
        # Set motorpositioner.motor = motor's PV.
        # Set motorpositioner.EGU = motor's EGU.
        motors = [
            e
            for e in ioc.raw_entities
            if e.get("type", "").endswith("dls_pmac_asyn_motor")
            and e.get("name") == entity.motor
        ]

        if len(motors) != 1:
            raise ValueError(
                f"Expected one motor with name '{entity.motor}', found {len(motors)}"
            )

        motor = motors[0]
        try:
            motor_pv = motor["P"] + motor["M"]
        except KeyError as ex:
            raise ValueError(
                f"Motor '{motor['name']}' missing required attribute {ex!s}"
            ) from ex
        entity.motor = motor_pv
        entity.EGU = motor.get("EGU", "")
