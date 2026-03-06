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
    ]:
        if entity_type == "dls_pmac_cs_asyn_motor":
            entity.type = "pmac.dls_pmac_asyn_motor"
            entity.is_cs = True
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
