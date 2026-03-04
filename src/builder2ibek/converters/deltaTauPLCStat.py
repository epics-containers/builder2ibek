import re

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "deltaTauPLCStat"

# Patterns to distinguish DTPSController from DTPSControllerNames in raw entities.
# The XML only includes non-default attributes, so p00 may not be present.
_RE_PBOOL = re.compile(r"^p\d\d$")
_RE_PNAME = re.compile(r"^p\d\dname$")


def _is_dtps_controller(raw):
    """True if raw entity is a DTPSController (has pNN boolean flags)."""
    return raw.get("globalHelper") and any(_RE_PBOOL.match(k) for k in raw)


def _is_dtps_controller_names(raw):
    """True if raw entity is a DTPSControllerNames (has pNNname string flags)."""
    return raw.get("globalHelper") and any(_RE_PNAME.match(k) for k in raw)


def _find_raw_controller(ioc, number, globalHelper):
    """Find DTPSController raw entity by number and globalHelper."""
    for raw in ioc.raw_entities:
        if (
            raw.get("globalHelper") == globalHelper
            and raw.get("number") == number
            and _is_dtps_controller(raw)
        ):
            return raw
    return None


def _find_raw_controller_names(ioc, number, globalHelper):
    """Find DTPSControllerNames raw entity by number and globalHelper."""
    for raw in ioc.raw_entities:
        if (
            raw.get("globalHelper") == globalHelper
            and raw.get("number") == number
            and _is_dtps_controller_names(raw)
        ):
            return raw
    return None


def _get_plc_mask(raw):
    """Compute lower and upper PLC bitmasks from p00..p31 boolean flags.

    Works with raw entities where booleans are still strings ("True"/"False")
    and only non-default (True) flags are present in the dict.
    """
    lower_mask = 0
    upper_mask = 0
    for i in range(16):
        val_lo = raw.get(f"p{i:02d}")
        val_hi = raw.get(f"p{i + 16:02d}")
        if val_lo == "True" or val_lo is True:
            lower_mask += 2**i
        if val_hi == "True" or val_hi is True:
            upper_mask += 2**i
    return lower_mask, upper_mask


def _find_dom_from_global(ioc, global_name):
    """Find the dom value from the DTPSGlobal raw entity."""
    for raw in ioc.raw_entities:
        # DTPSGlobal has no XML 'type' attribute, so raw type is still the
        # ibek entity type: "deltaTauPLCStat.DTPSGlobal"
        if raw.get("type") == "deltaTauPLCStat.DTPSGlobal":
            if raw.get("name") == global_name:
                return raw.get("dom")
    return None


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    Converter for deltaTauPLCStat module.

    The builder.py has three user-facing Device classes (DTPSGlobal,
    DTPSController, DTPSControllerNames) that programmatically create
    AutoSubstitution template instances. This converter decomposes them
    into their constituent template-level ibek entities.

    The XML 'type' attribute (STEP/PMAC) collides with ibek's reserved
    'type' field, so decomposed entities use 'controller_type' instead.
    The support YAML explicitly maps controller_type -> type in db args.
    """

    if entity_type == "DTPSGlobal":
        dom = entity.get("dom")
        sendsms = entity.get("sendSms") or ""
        global_name = entity.get("name")

        # Create 32 ControllerPLCStat per controller type (STEP and PMAC)
        for ctrl_type in ["STEP", "PMAC"]:
            for i in range(1, 33):
                entity.add_entity(
                    {
                        "type": "deltaTauPLCStat.ControllerPLCStat",
                        "controller_type": ctrl_type,
                        "dom": dom,
                        "number": f"{i:02d}",
                        "sendsms": sendsms,
                    }
                )

        # Scan raw_entities for DTPSController entries referencing this global
        # to compute active-controller bitmasks per type.
        active = {"STEP": [False] * 32, "PMAC": [False] * 32}
        for raw in ioc.raw_entities:
            if _is_dtps_controller(raw) and raw.get("globalHelper") == global_name:
                # raw["type"] contains the XML attribute value (STEP/PMAC),
                # not the ibek entity type.
                ctrl_type = raw.get("type")
                ctrl_num = raw.get("number")
                if isinstance(ctrl_num, str):
                    ctrl_num = int(ctrl_num)
                if ctrl_type in active and 1 <= ctrl_num <= 32:
                    active[ctrl_type][ctrl_num - 1] = True

        # Create ControllerGlobalPLCStatusLogic per type
        for ctrl_type in ["STEP", "PMAC"]:
            lower = 0
            upper = 0
            for i in range(16):
                if active[ctrl_type][i]:
                    lower += 2**i
                if active[ctrl_type][i + 16]:
                    upper += 2**i
            entity.add_entity(
                {
                    "type": "deltaTauPLCStat.ControllerGlobalPLCStatusLogic",
                    "controller_type": ctrl_type,
                    "dom": dom,
                    "activeControllersLower": lower,
                    "activeControllersUpper": upper,
                    "source": "globalPLCStatus",
                }
            )

        # Create GlobalPLCStatus
        entity.add_entity(
            {
                "type": "deltaTauPLCStat.GlobalPLCStatus",
                "dom": dom,
                "name": global_name,
            }
        )

        entity.delete_me()

    elif entity_type == "DTPSController":
        entity.remove("name")
        global_name = entity.get("globalHelper")
        ctrl_num = entity.get("number")
        if isinstance(ctrl_num, str):
            ctrl_num = int(ctrl_num)

        # Recover original XML type attribute (STEP/PMAC) from raw entities
        raw = _find_raw_controller(ioc, ctrl_num, global_name)
        ctrl_type = raw.get("type") if raw else None

        # Find the dom from the DTPSGlobal
        dom = _find_dom_from_global(ioc, global_name)

        # Compute PLC bitmasks from the raw entity
        lower_mask, upper_mask = _get_plc_mask(raw) if raw else (0, 0)

        entity.add_entity(
            {
                "type": "deltaTauPLCStat.ControllerCorrectPLCStat",
                "controller_type": ctrl_type,
                "dom": dom,
                "number": f"{ctrl_num:02d}",
                "lowerMask": lower_mask,
                "upperMask": upper_mask,
            }
        )

        entity.delete_me()

    elif entity_type == "DTPSControllerNames":
        entity.remove("name")
        global_name = entity.get("globalHelper")
        ctrl_num = entity.get("number")
        if isinstance(ctrl_num, str):
            ctrl_num = int(ctrl_num)

        # Recover original XML type attribute (STEP/PMAC) from raw entities
        raw = _find_raw_controller_names(ioc, ctrl_num, global_name)
        ctrl_type = raw.get("type") if raw else None

        # Find the dom from the DTPSGlobal
        dom = _find_dom_from_global(ioc, global_name)

        # Create 32 ControllerPLCName entities
        for i in range(32):
            plc_name = raw.get(f"p{i:02d}name") if raw else ""
            if plc_name is None:
                plc_name = ""
            entity.add_entity(
                {
                    "type": "deltaTauPLCStat.ControllerPLCName",
                    "controller_type": ctrl_type,
                    "dom": dom,
                    "number": f"{ctrl_num:02d}",
                    "plc_num": f"{i:02d}",
                    "plc_name": plc_name,
                }
            )

        entity.delete_me()
