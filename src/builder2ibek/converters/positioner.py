from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "positioner"

schema = ""

GDA_PLUGINS = Path(__file__).parent / "gdaPlugins.yaml"

# the types XMLbuilder registers with their multipositioner via addPositioner
SLOT_TYPES = ("positioner.positioner", "positioner.motorpositioner")

# the multipositioner's dfanout records have outputs OUTA..OUTH
MAX_SLOTS = 8

# GUI macros that XMLbuilder's multipositioner computes from its positioners
GUI_MACROS = ("NPOS", *(f"P{i}" for i in range(1, MAX_SLOTS + 1)))


def assign_slot(entity: Entity, ioc: Generic_IOC):
    """
    Set pos, the positioner's slot in its multipositioner, unless the XML
    gives one. As in XMLbuilder's multipositioner.addPositioner, positioners
    and motorpositioners take the slots A, B, C ... in the order they appear
    in the XML.
    """
    if entity.get("pos"):
        return
    taken = [
        e
        for e in ioc.already_converted
        if e.get("type") in SLOT_TYPES and e.get("MP") == entity.MP
    ]
    if len(taken) >= MAX_SLOTS:
        raise ValueError(
            f"Multipositioner '{entity.MP}' has more than {MAX_SLOTS} positioners"
        )
    entity.pos = chr(ord("A") + len(taken))


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "positioner":
        entity.DEADBAND = str(entity.DEADBAND)
        entity.remove("name")
        assign_slot(entity, ioc)

    elif entity_type == "motorpositioner":
        name = entity.get("name") or entity.get("Q")
        entity.remove("name")
        assign_slot(entity, ioc)

        # motorpositioner.template links to the motor as $(P)$(motor), with P
        # taken from the parent multipositioner. So motor is the motor record's
        # suffix, not its full PV. The motor is any motor record type, found
        # by name; its record is $(P)$(M), or $(P)$(Q) for softMotorForPiezo.
        # The motor's P must match the parent's, or the links would point at
        # another device. EGU is copied from the motor.
        motors = [e for e in ioc.raw_entities if e.get("name") == entity.motor]

        if len(motors) != 1:
            raise ValueError(
                f"Expected one entity named '{entity.motor}' as the motor of "
                f"motorpositioner '{name}', found {len(motors)}"
            )

        motor = motors[0]
        motor_type = motor.get("type", "")
        motor_pv = motor.get("M", motor.get("Q"))
        if motor.get("P") is None or motor_pv is None:
            raise ValueError(
                f"Motor '{motor['name']}' of type '{motor_type}' has no P with M "
                f"or Q, so its motor record PV is unknown"
            )

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

        entity.motor = motor_pv
        entity.EGU = motor.get("EGU", "")

    elif entity_type == "motorpositioner_external_motor":
        # takes P, MP, motor and pos as given, and nothing refers to its name
        entity.remove("name")

    elif entity_type == "multipositioner":
        # XMLbuilder recomputes these from the positioners, for its screens
        for macro in GUI_MACROS:
            entity.remove(macro)

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
