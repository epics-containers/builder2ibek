from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BLGui"

# parameter types of the BLGui entity models in ibek-support-dls
STATUS_STR = ["P", "CALC"] + [f"INP{c}" for c in "ABCDEFGHIJKL"]
STATUS_INT = ["PHAS"]
DEVICE_STR = ["P", "SHORTNAME", "DESCRIPTION", "GDA_NAME", "GDA_DESC", "BL_SECTION"]
DEVICE_INT = ["NFLOW", "NTEMP", "NCURR", "MTYPE", "BL_ORDER"]


def _coerce(entity: Entity, str_params: list[str], int_params: list[str]):
    # the generic converter turns numeric-looking XML values into numbers
    # (e.g. CALC="0", INPA="0") and keeps zero-padded ones as strings
    for p in str_params:
        if entity.get(p) is not None:
            entity[p] = str(entity[p])
    for p in int_params:
        # a cross-reference such as $(NTEMP) arrives as a Jinja string that
        # ibek renders; leave it for ibek to resolve
        if entity.get(p) is not None and not _is_jinja(entity[p]):
            entity[p] = int(entity[p])


def _is_jinja(value) -> bool:
    return isinstance(value, str) and "{{" in value


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BLGui support module

    By default every BLGui entity is dropped: most generic IOC images do not
    include the BLGui module, so its entities would fail schema validation.

    With `xml2yaml --blgui` (for generic IOCs whose binary includes BLGui,
    such as the RTEMS / DLS-build hybrids) auto_BLGui_status and
    auto_BLGui_device become BLGui.status and BLGui.device: they serve the
    DEVSTA / INFO PVs that synoptic screens read. The other BLGui entities
    are EDM display support only and are dropped either way.
    """
    # name is a gui association label, not referenced by other entities
    entity.remove("name")

    if not ioc.blgui:
        entity.delete_me()

    elif entity_type == "auto_BLGui_status":
        entity.type = "BLGui.status"
        _coerce(entity, STATUS_STR, STATUS_INT)

    elif entity_type == "auto_BLGui_device":
        entity.type = "BLGui.device"
        # some XMLs omit BL_SECTION / BL_ORDER; the model requires both, and
        # they only feed a gda comment tag in BLGui-device.template.
        if entity.get("BL_SECTION") is None:
            entity.BL_SECTION = ""
        if entity.get("BL_ORDER") is None:
            entity.BL_ORDER = 0
        _coerce(entity, DEVICE_STR, DEVICE_INT)

    else:
        entity.delete_me()
