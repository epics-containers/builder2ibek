from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motorPLC"

AXIS_TYPES = ["NX102_MotorAxis", "NX102_MotorAxisPot"]
N_AXES = 8

# parameters that the support YAML types as str but the XML parser makes numeric
STR_PARAMS = [
    "VELO",
    "TWV",
    "DHLM",
    "DLLM",
    "OFF",
    "home_velo",
    "fe_lim",
    "ERES",
    "MRES",
    "RRES",
    "URIP",
    "UEIP",
    "RDBD",
    "pot_period",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
]


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the motorPLC support module
    """
    if entity_type == "NX102_MotorController":
        # name stays as the id the axes refer to; timeout is unused by ibek
        entity.remove("timeout")

    elif entity_type in AXIS_TYPES:
        # name is kept: it is passed to the axis templates as a macro
        for param in STR_PARAMS:
            if param in entity and entity[param] is not None:
                entity[param] = str(entity[param])

        # builder.py Finalise() made a spare axis for every unused address.
        # Add them with the controller's last axis: extras are emitted before
        # the entity that adds them, and they must follow the controller
        axes = [
            e
            for e in ioc.raw_entities
            if e["type"] in [f"motorPLC.{t}" for t in AXIS_TYPES]
            and e.get("controller") == entity.controller
        ]
        if axes and axes[-1].get("ADDR") == entity.ADDR:
            used = {int(e["ADDR"]) for e in axes}
            spares = [a for a in range(1, N_AXES + 1) if a not in used]
            for spare_no, addr in enumerate(spares, start=1):
                entity.add_entity(
                    {
                        "type": "motorPLC.NX102_MotorAxisSpare",
                        "controller": entity.controller,
                        "ADDR": addr,
                        "spare_no": spare_no,
                    }
                )
