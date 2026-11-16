import codecs
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"

# the raw records file, written next to the ioc.yaml and loaded from there
RECORDS_DB = "records.db"
LOAD_COMMAND = f"dbLoadRecords config/{RECORDS_DB}"
LOAD_ENTITY = {"type": "epics.StartupCommand", "command": LOAD_COMMAND}
# the first line of a records.db that builder2ibek writes; a records.db without
# it is someone's own, which builder2ibek never overwrites or removes
HEADER_START = "# Raw records from the records.* elements of "
# the warning that says where the raw records went contains this
WRITTEN = f"written to config/{RECORDS_DB}"

# XML attributes of a records.* element that are not record fields: record is
# the record name and name is the builder's GUI label
NOT_FIELDS = {"record", "name"}

# The record fields ether_ip.ao carries: record is the record name, OUT becomes
# port and tag, SCAN becomes scan. name is the builder's GUI label.
ETHER_IP_AO_FIELDS = {"record", "name", "DTYP", "OUT", "SCAN"}


def _ether_ip_ao(entity: Entity, ioc: Generic_IOC) -> bool:
    """Turn a records.ao with DTYP EtherIP into an ether_ip.ao.

    The OUT link is "@<port> <tag>[ <flags>]", for example
    "@VLVCC_01_EIP GB_Index_Setpoint S 0.5". ether_ip_ao.template writes
    "@$(port) $(tag)", so the tag carries the flags, such as the scan period
    "S <seconds>", unchanged. scan is the record's SCAN field, Passive when the
    XML leaves it out. Returns False if OUT is not an EtherIP link.
    """
    xml = entity.xml_attributes()
    port, _, tag = xml.get("OUT", "").strip().removeprefix("@").partition(" ")
    if not xml.get("OUT", "").strip().startswith("@") or not port or not tag:
        return False

    dropped = sorted(k for k in xml if k not in ETHER_IP_AO_FIELDS)
    if dropped:
        fields = ", ".join(f"{k}={xml[k]}" for k in dropped)
        ioc.extra_warnings.append(
            f"{ioc.source_file.stem}: records.ao {xml['record']} became "
            f"ether_ip.ao, which has no field for {fields}: those fields are "
            f"left out of the record"
        )

    for key in list(entity.keys()):
        if key != "type":
            del entity[key]
    entity.type = "ether_ip.ao"
    entity.record = xml["record"]
    entity.port = port
    entity.tag = tag.strip()
    entity.scan = xml.get("SCAN", "Passive")
    return True


def _decode(value: str) -> str:
    """A field value as builder wrote it: backslash escapes decoded"""
    try:
        return codecs.escape_decode(value.encode("latin-1"))[0].decode("latin-1")
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
    if (
        entity_type == "ao"
        and xml.get("DTYP") == "EtherIP"
        and _ether_ip_ao(entity, ioc)
    ):
        return
    if not xml.get("record"):
        ioc.wont_convert(entity, "a raw record with no record name")
        return
    name = _decode(xml["record"])
    fields = {k: _decode(v) for k, v in xml.items() if k not in NOT_FIELDS}
    entity.delete_me()
    if name in ioc.raw_records:
        # builder stops with "Record already defined" here
        ioc.extra_warnings.append(
            f"{ioc.source_file.stem}: records.{entity_type} {name} is defined "
            f"more than once in the XML: only the first, a "
            f"records.{ioc.raw_records[name][0]}, goes to {RECORDS_DB}"
        )
        return
    ioc.raw_records[name] = (entity_type, fields)


def render_records(records: dict[str, tuple[str, dict[str, str]]]) -> str:
    """
    The records in builder's <IOC>.db layout: records sorted by name, each
    record's fields sorted, and field names padded to four characters
    """
    blocks = []
    for name in sorted(records):
        record_type, fields = records[name]
        lines = [f'record({record_type}, "{name}")', "{"]
        for key in sorted(fields):
            pad = " " * (4 - len(key))
            lines.append(f'    field({key}, {pad}"{fields[key]}")')
        lines.append("}")
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def finalize(ioc: Generic_IOC):
    """
    Write the IOC's raw records to records.db next to the ioc.yaml and load
    them with an epics.StartupCommand. ibek's st.cmd loads ioc.db after every
    entity's startup commands, so these records load just before ioc.db.
    """
    if not ioc.raw_records:
        return
    source = ioc.source_file.name
    header = (
        f"{HEADER_START}{source},\n# loaded by an epics.StartupCommand in ioc.yaml.\n\n"
    )
    ioc.side_files[RECORDS_DB] = header + render_records(ioc.raw_records)
    # Load order: st.cmd runs startup commands before it loads ioc.db, so the
    # raw records load BEFORE the template records. builder's IOCs load
    # <IOC>.db AFTER the expanded db, which is the order wanted; this command
    # is the place to change once ibek can load a file after ioc.db.
    ioc.entities.append(dict(LOAD_ENTITY))
    count = len(ioc.raw_records)
    plural = "record" if count == 1 else "records"
    ioc.extra_warnings.append(
        f"{ioc.source_file.stem}: {count} raw {plural} {WRITTEN} as builder "
        f"wrote them, hardware DTYPs included, "
        f"and loaded by an epics.StartupCommand before ioc.db: check that "
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
    The IOC's raw records then go nowhere: the side file, its StartupCommand
    and the note about them are taken out, and a warning says so.
    """
    path = folder / RECORDS_DB
    if not path.exists() or generated(path):
        return
    count = len(ioc.raw_records)
    ioc.side_files.pop(RECORDS_DB, None)
    ioc.entities = [e for e in ioc.entities if dict(e) != LOAD_ENTITY]
    ioc.extra_warnings = [w for w in ioc.extra_warnings if WRITTEN not in w]
    text = (
        f"{ioc.source_file.stem}: {path} was not written by builder2ibek, so "
        f"it is left as it is"
    )
    if count:
        text += (
            f"; the XML's {count} raw records are not written: add any that "
            f"are still wanted to that file"
        )
    ioc.extra_warnings.append(text)
