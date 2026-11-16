import codecs

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"

# the raw records file, written next to the ioc.yaml and loaded from there
RECORDS_DB = "records.db"
LOAD_COMMAND = f"dbLoadRecords config/{RECORDS_DB}"

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
    fields = {k: _decode(v) for k, v in xml.items() if k not in NOT_FIELDS}
    ioc.raw_records[_decode(xml["record"])] = (entity_type, fields)
    entity.delete_me()


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
        f"# Raw records from the records.* elements of {source},\n"
        f"# loaded by an epics.StartupCommand in ioc.yaml.\n\n"
    )
    ioc.side_files[RECORDS_DB] = header + render_records(ioc.raw_records)
    ioc.entities.append({"type": "epics.StartupCommand", "command": LOAD_COMMAND})
    count = len(ioc.raw_records)
    plural = "record" if count == 1 else "records"
    ioc.extra_warnings.append(
        f"{ioc.source_file.stem}: {count} raw {plural} written to "
        f"config/{RECORDS_DB} as builder wrote them, hardware DTYPs included, "
        f"and loaded by an epics.StartupCommand before ioc.db: check that "
        f"each is still wanted"
    )
