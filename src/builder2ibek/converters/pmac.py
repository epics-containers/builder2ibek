"""
The convertor handler module for pmac support module
"""

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

# The prefix for Builder XML Tags that this support module uses
xml_component = "pmac"

# The ibek schema for the Generic IOC that compiles this support module
# (currently not used) TODO it would be good to pull in the schema and
# verify that the YAML we generate is valid against it.
schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/download/"
    "2023.11.1/ibek.ioc.schema.json"
)

# entity types that create a pmac controller port and take CSG0..CSG7
CONTROLLER_TYPES = ["pmac.PMAC", "pmac.GeoBrick", "pmac.PowerPMAC"]

# pmacController.template only has state strings for groups 0 to 7
MAX_CS_GROUP = 7


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pmac support module
    """
    # remove redundant parameters
    entity.remove("gda_desc")
    entity.remove("gda_name")

    if entity_type == "pmacDisableLimitsCheck":
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type in [
        "dls_pmac_asyn_motor",
        "dls_pmac_cs_asyn_motor",
        "dls_pmac_asyn_motor_no_coord",
    ]:
        if entity_type == "dls_pmac_cs_asyn_motor":
            entity.type = "pmac.dls_pmac_asyn_motor"
            entity.is_cs = True
        elif entity_type == "dls_pmac_asyn_motor_no_coord":
            entity.type = "pmac.dls_pmac_asyn_motor"
            entity.is_cs = False
        # standardise the name of the controller port
        entity.rename("PORT", "Controller")
        # this is calculated
        entity.remove("SPORT")
        # remove GUI only parameters
        entity.remove("name")
        # convert to enum
        if entity.DIR == 1:
            entity.DIR = "Neg"
        else:
            entity.DIR = "Pos"
        # convert to enum
        if entity.UEIP == 1:
            entity.UEIP = "Yes"
        else:
            entity.UEIP = "No"
        if entity.FOFF == 1:
            entity.FOFF = "Frozen"
        else:
            entity.FOFF = "Variable"
        # ensure string params stay as strings when XML parses them as int
        if hasattr(entity, "INIT") and entity.INIT is not None:
            entity.INIT = str(entity.INIT)
        if hasattr(entity, "HOME") and entity.HOME is not None:
            entity.HOME = str(entity.HOME)
        # HLM/LLM: default to 0.0 when unset or blank; coerce to float otherwise
        for field in ("HLM", "LLM"):
            val = entity.get(field)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                entity[field] = 0.0
            elif not isinstance(val, float):
                entity[field] = float(val)
        # convert NTM to enum
        ntm = entity.get("NTM")
        if ntm is not None:
            entity.NTM = "YES" if ntm == 1 else "NO"

    elif entity_type == "auto_translated_motor":
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type == "GeoBrick":
        entity.rename("Port", "pmacAsynPort")
        # remove XML-builder GUI-only attributes
        entity.remove("ControlIP")
        entity.remove("ControlMode")
        entity.remove("ControlPort")
        entity.remove("Description")

    elif entity_type == "PowerPMAC":
        # standardise the name of the SSH port reference
        entity.rename("Port", "pmacAsynSSHPort")

    elif entity_type == "GeoBrickTrajectoryControlT":
        # don't bore the user with the fact this is a template!
        entity.type = "pmac.GeoBrickTrajectoryControl"
        # standardise the name of the controller port
        entity.rename("PORT", "PmacController")
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type == "autohome":
        # remove GUI only parameters
        entity.remove("name")
        # standardise the name of the controller port
        entity.rename("PORT", "PmacController")

    elif entity_type in ["pmacCreateCsGroup", "pmacCsGroupAddAxis"]:
        # remove GUI only parameters
        entity.remove("name")

    elif entity_type == "CS":
        # standardise the name of the controller port
        entity.rename("Controller", "PmacController")
        # this is calculated
        entity.remove("PARENTPORT")
        # this is a redundant parameter
        entity.remove("PLCNum")

    elif entity_type == "CS_accel_dcm":
        # name is type: id in support YAML but only used for GUI association.
        # XML may not provide it, so generate a default if missing.
        if not entity.name:
            entity.name = f"{entity.P}_CS{entity.COORD}"

    elif entity_type in ["pmacVariableWrite", "pmacVariableReadLED"]:
        # remove GUI only parameters
        entity.remove("name")
        entity.remove("LABEL")

    elif entity_type == "pmacSetOpenLoopEncoderAxis":
        entity.rename("Axis", "AXIS")
        entity.rename("Controller", "CONTROLLER")
        entity.rename("Encoder_axis", "ENCODER_AXIS")

    elif entity_type == "pmacSetCoordStepsPerUnit":
        entity.rename("Axis", "AXIS")
        entity.rename("Scale", "SCALE")

    elif entity_type == "pmacAsynIPPort":
        entity.remove("simulation")
        if ":" not in entity.IP:
            entity.IP = entity.IP + ":1025"

    elif entity_type == "RunCommand":
        # XML uses BRICK but support YAML expects PORT
        entity.rename("BRICK", "PORT")

    elif entity_type == "RunPlc":
        # XML uses BRICK but support YAML expects PORT
        entity.rename("BRICK", "PORT")

    elif entity_type == "moveAxesToSafeMaster":
        # name is type: id (slaves reference it via MASTER)
        pass  # no special conversion needed

    elif entity_type == "moveAxesToSafeSlave":
        # Assign axis number N by counting preceding slaves that share the
        # same MASTER value.  Identify "this" entity by matching AXIS + MASTER.
        master_name = entity.MASTER
        n = 0
        for raw in ioc.raw_entities:
            raw_type = raw.get("type", "")
            if (
                raw_type == "pmac.moveAxesToSafeSlave"
                and raw.get("MASTER") == master_name
            ):
                n += 1
                if raw.get("AXIS") == entity.AXIS:
                    break
        entity.N = n
        # name is GUI-only; slaves are not cross-referenced
        entity.remove("name")

    elif entity_type in ["auto_pmacStatus8Axes", "auto_pmacStatus32Axes"]:
        # These entities are auto-created by GeoBrick/PowerPMAC in builder.py
        # but arrive from XML with no attributes. Find the last controller
        # in raw_entities and inject its PMAC (P) and PORT (name).
        for raw in reversed(ioc.raw_entities):
            raw_type = raw.get("type", "")
            if raw_type in ["pmac.GeoBrick", "pmac.PowerPMAC"]:
                entity.PMAC = raw.get("P", "")
                entity.PORT = raw.get("name", "")
                break


def _sort_keys(entity: dict):
    """
    Restore the key order that do_dispatch applies: type first, then the
    remaining keys sorted. finalize runs after that sort, so an entity it
    adds a key to has to be put back in order itself.
    """
    sorted_items = dict(sorted(entity.items()))
    entity_type = sorted_items.pop("type")
    entity.clear()
    entity["type"] = entity_type
    entity.update(sorted_items)


def finalize(ioc: Generic_IOC):
    """
    Copy each coordinate system group's name onto its controller.

    pmacCreateCsGroup names the group, but the COORDINATE_SYS_GROUP mbbo takes
    its state strings from the controller's CSG0..CSG7 template arguments.
    Converting the group on its own left every CSGn empty, so the groups could
    not be selected from an OPI screen - see ioc-pmac#40.
    """
    entities: list[Entity] = ioc.entities  # type: ignore

    controllers = {
        entity["name"]: entity
        for entity in entities
        if entity.get("type") in CONTROLLER_TYPES and entity.get("name")
    }
    if not controllers:
        return

    modified: list[str] = []
    for entity in entities:
        if entity.get("type") != "pmac.pmacCreateCsGroup":
            continue

        group_name = entity.get("GroupName")
        group_number = entity.get("GroupNumber")
        controller = controllers.get(entity.get("Controller"))
        if controller is None or not group_name:
            continue

        if not isinstance(group_number, int) or not 0 <= group_number <= MAX_CS_GROUP:
            print(
                f"Warning: coordinate system group {group_name} has GroupNumber "
                f"{group_number}, outside the range 0..{MAX_CS_GROUP} that "
                "pmacController.template supports - its name is dropped"
            )
            continue

        csg = f"CSG{group_number}"
        if controller.get(csg):
            # the controller already names this group, leave it alone
            continue
        controller[csg] = group_name
        if entity["Controller"] not in modified:
            modified.append(entity["Controller"])

    for name in modified:
        _sort_keys(controllers[name])
