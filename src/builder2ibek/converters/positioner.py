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
        entity.remove("name")

    elif entity_type == "motorpositioner":
        entity.remove("name")

        # Find the dls_pmac_asyn_motor whose name = original motorpositioner.motor.
        # There is also dls_pmac_cs_asyn_motor but I don't need it for B21 IOCs,
        # so leave it out of the search for now.
        # Get the motor's PV and EGU
        # Set motorpositioner.motor based on motor type
        # Set motorpositioner.EGU to the motor's EGU
        motor_types = (
            "dls_pmac_asyn_motor",
            "basic_asyn_motor",
            "softMotorForPiezo",
        )
        motors = [
            e
            for e in ioc.raw_entities
            if any(e.get("type", "").endswith(t) for t in motor_types)
            and e.get("name") == entity.motor
        ]

        if len(motors) != 1:
            raise ValueError(
                f"Expected one motor with name '{entity.motor}', found {len(motors)}"
            )

        motor = motors[0]

        # motor is stored as a suffix, not a PV: motorpositioner.template
        # resolves it as $(P)$(motor).RBV, and the motorpositioner takes its P
        # from the parent multipositioner. That is only correct while the two
        # prefixes agree, so XMLbuilder asserted it:
        #
        #     assert motor.args['P'] == args['P'], \
        #         "Motor prefix must match motor positioner prefix"
        #
        # Without the check a mismatch is silent, and the record links to a
        # device that may not even exist. Only checked when the parent resolves;
        # a dangling MP reference is ibek's error to report, not ours.
        parents = [
            e
            for e in ioc.raw_entities
            if e.get("type", "").endswith("multipositioner")
            and e.get("name") == entity.MP
        ]
        if len(parents) == 1 and parents[0].get("P") != motor.get("P"):
            raise ValueError(
                f"motor '{motor['name']}' prefix '{motor.get('P')}' does not "
                f"match multipositioner '{entity.MP}' prefix "
                f"'{parents[0].get('P')}' — motorpositioner.template resolves "
                f"the motor as $(P)$(motor)"
            )

        # softMotorForPiezo uses Q; pmac/basic motors use M
        if motor.get("type", "").endswith("softMotorForPiezo"):
            try:
                motor_pv = motor["Q"]
            except KeyError as ex:
                raise ValueError(
                    f"Motor '{motor['name']}' missing required attribute {ex!s}"
                ) from ex
        else:
            try:
                motor_pv = motor["M"]
            except KeyError as ex:
                raise ValueError(
                    f"Motor '{motor['name']}' missing required attribute {ex!s}"
                ) from ex
        entity.motor = motor_pv
        entity.EGU = motor.get("EGU", "")
