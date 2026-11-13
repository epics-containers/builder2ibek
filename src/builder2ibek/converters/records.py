from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "records"

REASON = (
    "raw records have no entity model: recreate any that are still needed "
    "as a template in the IOC instance's config folder or in a support "
    "module (docs/how-to/after-beamline-convert.md, Custom templates)"
)

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


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for raw records

    A records.ao with DTYP EtherIP becomes an ether_ip.ao. builder2ibek won't
    convert any other raw record: each one is left out, with one warning per
    record type naming the IOC and how many were dropped.
    """
    if (
        entity_type == "ao"
        and entity.xml_attributes().get("DTYP") == "EtherIP"
        and _ether_ip_ao(entity, ioc)
    ):
        return
    ioc.wont_convert(entity, REASON)
