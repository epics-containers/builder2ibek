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

        # motorpositioner.template links to the motor as $(P)$(motor), with P
        # taken from the parent multipositioner. So motor is the motor record's
        # suffix, not its full PV: M for pmac and basic motors, Q for
        # softMotorForPiezo. As in XMLbuilder, the motor's P must match the
        # parent's, or the links would point at another device.
        # EGU is copied from the motor.
        motor_types = (
            "dls_pmac_asyn_motor",
            "dls_pmac_asyn_motor_no_coord",
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
        parents = [
            e
            for e in ioc.raw_entities
            if e.get("type", "").endswith("multipositioner")
            and e.get("name") == entity.MP
        ]
        if len(parents) != 1:
            raise ValueError(
                f"Expected one multipositioner with name '{entity.MP}', "
                f"found {len(parents)}"
            )
        if motor.get("P") != parents[0].get("P"):
            raise ValueError(
                f"Motor '{motor['name']}' prefix '{motor.get('P')}' does not match "
                f"multipositioner '{entity.MP}' prefix '{parents[0].get('P')}'"
            )

        motor_pv = motor.get("M", motor.get("Q"))
        if motor_pv is None:
            raise ValueError(f"Motor '{motor['name']}' has neither M nor Q")
        entity.motor = motor_pv
        entity.EGU = motor.get("EGU", "")

    elif entity_type == "multipositioner":
        # First we need to check if there is a corresponding motorpositioner that
        # already has a Q (and therefore a PS) macro defined
        motor_ps = [
            e
            for e in ioc.raw_entities
            if e.get("type", "").endswith("motorpositioner")
            and e.get("MP") == entity.name
        ]
        if len(motor_ps) == 1 and motor_ps[0].get("Q"):
            entity["PS"] = motor_ps[0].get("Q")

        else:
            # Multiposioner allows for up to 6 nested multipositioners, however we do
            # not want this nested logic to exist in future. This is especially the case
            # as it was handled inside of builder.py for positioner.
            # We will manually append the corresponding PS macro, which identifies what
            # positioner of the multipositioner it is.

            # We need the name to determine the number of positioners that have already
            # been converted for this combination of P and MP.
            converted_mps = [
                e
                for e in ioc.already_converted
                if e.get("type", "").endswith("multipositioner")
                and e.get("P") == entity.P
                and e.get("MP") == entity.MP
            ]

            ps_number = len(converted_mps) + 1
            if ps_number > 6:
                raise ValueError(
                    "A multipositioner supports at most six sub-positioners"
                )
            # Assign the corresponding PS macro (P1, P2, ...)
            entity["PS"] = f":P{ps_number}"

        # TODO: We need to check if POSN is defined (i.e. the builder object
        # is not used)
        # posn = entity.get("posn", "")
        # if posn is not None:
        #     try:
        #         posn = int(posn)
        #     except ValueError:
        #         # POSN exists but isn't an
        #         pass
