import codecs
import warnings
from collections.abc import Callable
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"

# the raw records file, written next to the ioc.yaml and loaded from there
RECORDS_DB = "records.db"
# the first line of a records.db that builder2ibek writes; a records.db without
# it is someone's own, which builder2ibek never overwrites or removes
HEADER_START = "# Raw records from the records.* elements of "
# the warning that says where the raw records went contains this
WRITTEN = f"written to config/{RECORDS_DB}"

# XML attributes of a records.* element that are not record fields: record is
# the record name and name is the builder's GUI label
NOT_FIELDS = {"record", "name"}


# the values of the ao record's PRIO menu, in menu index order: the ether_ip.ao
# PRIO enum
PRIORITIES = ("LOW", "MEDIUM", "HIGH")


def _int(value: str) -> int:
    """value as an int. Raises ValueError for one that is not a whole number,
    such as 2.5."""
    number = float(value)
    if not number.is_integer():
        raise ValueError(value)
    return int(number)


def _priority(value: str) -> str:
    """
    A PRIO value as the ether_ip.ao PRIO enum: a menu index (0, 1 or 2) or a
    menu name in any case. Raises ValueError for any other value.
    """
    value = value.strip()
    if value in ("0", "1", "2"):
        return PRIORITIES[int(value)]
    if value.upper() in PRIORITIES:
        return value.upper()
    raise ValueError(value)


# Record fields ether_ip.ao takes as parameters of the same name, each with the
# function that turns its value into the model's type, raising ValueError for a
# value that the type cannot hold, such as an empty DRVH
ETHER_IP_AO_PARAMS: dict[str, Callable[[str], float | int | str]] = {
    "DRVH": float,
    "DRVL": float,
    "PREC": _int,
    "PRIO": _priority,
    "VAL": str,
}

# The record fields ether_ip.ao carries: record is the record name, OUT becomes
# port and tag, SCAN becomes scan, and the ETHER_IP_AO_PARAMS keep their names.
# name is the builder's GUI label.
ETHER_IP_AO_FIELDS = {"record", "name", "DTYP", "OUT", "SCAN", *ETHER_IP_AO_PARAMS}


def _ether_ip_ao(entity: Entity, ioc: Generic_IOC) -> bool:
    """Turn a records.ao with DTYP EtherIP into an ether_ip.ao.

    The OUT link is "@<port> <tag>[ <flags>]", for example
    "@VLVCC_01_EIP GB_Index_Setpoint S 0.5". ether_ip_ao.template writes
    "@$(port) $(tag)", so the tag carries the flags, such as the scan period
    "S <seconds>", unchanged. scan is the record's SCAN field, Passive when the
    XML leaves it out. DRVH, DRVL, PREC, PRIO and VAL pass through when the XML
    has them; one whose value the model cannot take is warned about with the
    fields ether_ip.ao has no place for. Returns False if OUT is not an
    EtherIP link or the record has no name.
    """
    xml = entity.xml_attributes()
    port, _, tag = xml.get("OUT", "").strip().removeprefix("@").partition(" ")
    if not xml.get("OUT", "").strip().startswith("@") or not port or not tag:
        return False
    if not xml.get("record"):
        return False

    params, unusable = {}, []
    for key, kind in ETHER_IP_AO_PARAMS.items():
        if key in xml:
            try:
                params[key] = kind(xml[key])
            except ValueError:
                unusable.append(key)
    dropped = sorted(k for k in xml if k not in ETHER_IP_AO_FIELDS or k in unusable)
    if dropped:
        fields = ", ".join(f"{k}={xml[k]}" for k in dropped)
        ioc.extra_warnings.append(
            f"{ioc.source_file.stem}: records.ao {xml['record']} became "
            f"ether_ip.ao, which has no field for, or an unusable value of, "
            f"{fields}: those fields are left out of the record"
        )

    for key in list(entity.keys()):
        if key != "type":
            del entity[key]
    entity.type = "ether_ip.ao"
    entity.record = xml["record"]
    entity.port = port
    entity.tag = tag.strip()
    entity.scan = xml.get("SCAN", "Passive")
    entity.update(params)
    return True


def _decode(value: str) -> str:
    """
    A field value as builder wrote it: backslash escapes decoded. A backslash
    that starts no escape, as in \\d, stays as it is, as builder left it.
    """
    try:
        with warnings.catch_warnings():
            # escape_decode warns about such a backslash, then keeps it
            warnings.simplefilter("ignore", DeprecationWarning)
            decoded = codecs.escape_decode(value.encode("latin-1"))[0]
        return decoded.decode("latin-1")
    except (UnicodeEncodeError, ValueError):
        return value


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for raw records

    A records.ao with DTYP EtherIP becomes an ether_ip.ao. Every other raw
    record, whatever its DTYP, leaves the ioc.yaml and goes to records.db
    (see finalize), with its fields as builder wrote them.
    """
    xml = entity.xml_attributes()
    name = _decode(xml.get("record", ""))
    if _defined_before(name, entity_type, ioc):
        entity.delete_me()
        return
    if (
        entity_type == "ao"
        and xml.get("DTYP") == "EtherIP"
        and _ether_ip_ao(entity, ioc)
    ):
        ioc.converted_records[name] = "ether_ip.ao"
        return
    if not name:
        ioc.wont_convert(entity, "a raw record with no record name")
        return
    fields = {k: _decode(v) for k, v in xml.items() if k not in NOT_FIELDS}
    entity.delete_me()
    ioc.raw_records[name] = (entity_type, fields)


def _defined_before(name: str, entity_type: str, ioc: Generic_IOC) -> bool:
    """
    Whether an earlier records.* element defines the record name, which
    builder refuses with "Record already defined". The first one stays, and
    a warning names both.
    """
    if name in ioc.raw_records:
        first = f"a records.{ioc.raw_records[name][0]}, goes to {RECORDS_DB}"
    elif name in ioc.converted_records:
        first = f"a records.ao, becomes {ioc.converted_records[name]}"
    else:
        return False
    ioc.extra_warnings.append(
        f"{ioc.source_file.stem}: records.{entity_type} {name} is defined "
        f"more than once in the XML: only the first, {first}"
    )
    return True


def render_records(
    records: dict[str, tuple[str, dict[str, str]]],
    infos: dict[str, dict[str, str]] | None = None,
) -> str:
    """
    The records in builder's <IOC>.db layout: records sorted by name, each
    record's fields sorted, and field names padded to four characters; then
    each record's info tags, sorted
    """
    blocks = []
    for name in sorted(records):
        record_type, fields = records[name]
        lines = [f'record({record_type}, "{name}")', "{"]
        for key in sorted(fields):
            pad = " " * (4 - len(key))
            lines.append(f'    field({key}, {pad}"{fields[key]}")')
        for key, value in sorted((infos or {}).get(name, {}).items()):
            lines.append(f'    info({key}, "{value}")')
        lines.append("}")
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def finalize(ioc: Generic_IOC):
    """
    Write the IOC's raw records to records.db next to the ioc.yaml and list
    it in the ioc.yaml's post_db_files, which ibek loads after ioc.db. They
    include the records of userIO entities (see userIO.py).
    """
    if not ioc.raw_records:
        return
    source = ioc.source_file.name
    header = (
        f"{HEADER_START}{source},\n"
        f"# loaded after ioc.db through post_db_files in ioc.yaml.\n"
        f"# Do not edit: builder2ibek xml2yaml regenerates this file and\n"
        f"# overwrites any edit. Edit the XML instead.\n\n"
    )
    ioc.side_files[RECORDS_DB] = header + render_records(
        ioc.raw_records, ioc.raw_record_info
    )
    # ibek loads each post_db_files entry after ioc.db, so a raw record that
    # shares a name with a template record sets that record's fields, as in
    # builder's IOCs
    ioc.post_db_files.append(RECORDS_DB)
    count = len(ioc.raw_records)
    plural = "record" if count == 1 else "records"
    ioc.extra_warnings.append(
        f"{ioc.source_file.stem}: {count} raw {plural} {WRITTEN} as builder "
        f"wrote them, hardware DTYPs included, "
        f"and loaded after ioc.db through post_db_files: check that "
        f"each is still wanted"
    )


def generated(path: Path) -> bool:
    """Whether the records.db at path is one builder2ibek wrote"""
    try:
        with path.open(encoding="latin-1") as f:
            return f.readline().startswith(HEADER_START)
    except OSError:
        return False


def keep_own_records_db(ioc: Generic_IOC, folder: Path):
    """
    Leave a records.db in folder alone when builder2ibek did not write it.
    The IOC's raw records then go nowhere: the side file, its post_db_files
    entry and the note about them are taken out, and a warning says so.
    """
    path = folder / RECORDS_DB
    if not path.exists() or generated(path):
        return
    count = len(ioc.raw_records)
    ioc.side_files.pop(RECORDS_DB, None)
    ioc.post_db_files = [f for f in ioc.post_db_files if f != RECORDS_DB]
    ioc.extra_warnings = [w for w in ioc.extra_warnings if WRITTEN not in w]
    text = (
        f"{ioc.source_file.stem}: {path} was not written by builder2ibek, so "
        f"it is kept as it is. The ioc.yaml gets no post_db_files entry for "
        f"it: it is loaded only by whatever the ioc.yaml already does with it, "
        f"such as its own epics.StartupCommand"
    )
    if count:
        plural = "record" if count == 1 else "records"
        text += (
            f". {count} raw {plural} from the XML {'was' if count == 1 else 'were'} "
            f"not written. To have builder2ibek write and load them, rename or "
            f"remove the hand-written {RECORDS_DB}"
        )
    ioc.extra_warnings.append(text)
