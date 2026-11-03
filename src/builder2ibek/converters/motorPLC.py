from typing import Any

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "motorPLC"

AXIS_TYPES = [f"motorPLC.{t}" for t in ["NX102_MotorAxis", "NX102_MotorAxisPot"]]
N_AXES = 8

# parameter order in the generated ioc.yaml (the rest follow alphabetically)
param_order = [
    "name",
    "P",
    "M",
    "DESC",
    "controller",
    "ADDR",
    "DHLM",
    "DLLM",
    "ERES",
    "MRES",
    "current",
    "home_method",
    "pot_idx",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
]

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

    elif entity.type in AXIS_TYPES:
        # name is kept: it is passed to the axis templates as a macro
        for param in STR_PARAMS:
            if param in entity and entity[param] is not None:
                entity[param] = str(entity[param])


def finalize(ioc: Generic_IOC):
    """
    builder.py Finalise() made a spare axis for every unused address on each
    NX102_MotorController. Insert them after that controller's last real axis.
    This runs after the param_order sort, so keys are written in that order.
    """
    entities: list[dict[str, Any]] = ioc.entities

    controllers = [
        e["name"] for e in entities if e.get("type") == "motorPLC.NX102_MotorController"
    ]
    for controller in controllers:
        positions = [
            i
            for i, e in enumerate(entities)
            if e.get("type") in AXIS_TYPES and e.get("controller") == controller
        ]
        if positions:
            insert_at = positions[-1] + 1
            used = {int(entities[i]["ADDR"]) for i in positions}
        else:
            # no real axes: spares follow the controller itself
            insert_at = next(
                i + 1 for i, e in enumerate(entities) if e.get("name") == controller
            )
            used = set()

        spares = [a for a in range(1, N_AXES + 1) if a not in used]
        entities[insert_at:insert_at] = [
            {
                "type": "motorPLC.NX102_MotorAxisSpare",
                "controller": controller,
                "ADDR": addr,
                "spare_no": spare_no,
            }
            for spare_no, addr in enumerate(spares, start=1)
        ]
