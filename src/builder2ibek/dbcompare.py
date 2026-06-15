import re
from dataclasses import dataclass, field
from pathlib import Path

# extract record type, name and fields from an EPICS database file
regex_record = re.compile(
    r"^(?<!#) *record *\( *([^,]*), *\"?([^\"]*)\"? *\)[\s\S]*?{([\s\S]*?)}",
    re.MULTILINE,
)
# extract field name and value from the fields section of the above
regex_field = re.compile(
    r'^(?<!#) *field *\( *([^,]*), *"?([^"]*)"? *\)',
    re.MULTILINE,
)

# Record-name patterns that differ between the DLS-legacy devIocStats and the
# upstream version now shipped with ibek. Same set of differences appears in
# every converted IOC, so --skip-known folds them in.
KNOWN_DEVIOCSTATS_IGNORE = [
    # Removed: DLS-local extensions dropped by upstream.
    r":SRHEARTBT\b",
    r":(DLSVER|IOC_LOG_PORT|TIMEZONE)\b",
    # Removed: old naming for system-reset / reboot history slots.
    r":\d+:(STATUSST|STATUS|STATE|NAME|TIME)\b",
    r":(RR|SR)(STATUSST|STATUS|RECENTST|TIME)\b",
    # Added: upstream devIocStats system-reset history (SR_*).
    r":SR_\w+",
    # Added: callback queue and scan-once queue monitoring.
    r":CB(HIGH|MEDIUM|LOW)?_Q_\w+",
    r":SCANONCE_Q_\w+",
    # Added: CA server, IOC log file, misc diagnostics.
    r":CAS_\w+",
    r":IOC_LOG_FILE_\w+",
    r":(ABORT_ON_ASSERT|TZ)\b",
    # Present in both DBs but with template-level field differences.
    r":(STARTTOD|TOD)\b",
    r":\d*HZ_(MODE|UPD_TIME)\b",
]


@dataclass
class EpicsDb:
    path: Path
    text: str = ""
    records: set[str] = field(default_factory=lambda: set())
    fields: dict[str, set[str]] = field(default_factory=lambda: {})


@dataclass
class EpicsField:
    field_names: set[str] = field(default_factory=lambda: set())
    values: dict[str, str] = field(default_factory=lambda: {})


def normalize_float_records(s: set[str]) -> set[str]:
    normalised = set()
    for item in s:
        item = item.replace(" MS", "")
        item = item.replace(" PP", "")
        # in dlsPLC bi name "" is replaced with default "unused"
        item = item.replace("NAM unused", "NAM ")
        try:
            parts = item.split(maxsplit=1)
            if len(parts) == 1:
                # blank fields are the same as absent fields
                continue
            name, value = parts
            # default values can also be ignored
            if name == "SCAN" and value == "Passive":
                continue
            normalised.add(f"{name} {float(value)}")
        except (ValueError, IndexError):
            normalised.add(item)
    return normalised


def check_ignore_list(ignore: list[str], string: str) -> bool:
    for s in ignore:
        if re.findall(s, string):
            # print(f"ignoring record: {string}")
            return True
    return False


def compare_dbs(
    old_path: Path,
    new_path: Path,
    ignore: list[str],
    remove_duplicates: bool = False,
    skip_known: bool = True,
    output: Path | None = None,
):
    """
    validate that two DBs have the same set of records

    used to ensure that an IOC converted to epics-containers has the same
    records as the original builder IOC
    """
    if skip_known:
        ignore = [*ignore, *KNOWN_DEVIOCSTATS_IGNORE]

    old = EpicsDb(old_path)
    new = EpicsDb(new_path)

    for db in [old, new]:
        db.text = db.path.read_text()
        for record in regex_record.finditer(db.text):
            rec_str = f"{record.group(1)} {record.group(2)}"
            # throw away duplicates in the old db
            if rec_str in db.fields and db == old and remove_duplicates:
                continue
            # throw away records that match the ignore list
            if check_ignore_list(ignore, rec_str):
                continue
            db.records.add(rec_str)
            db.fields[rec_str] = set()
            for rec_field in regex_field.finditer(record.group(3)):
                field = f"{rec_field.group(1)} {rec_field.group(2)}"
                if check_ignore_list(ignore, field):
                    continue
                db.fields[rec_str].add(field)

    old_only = sorted(old.records - new.records)
    new_only = sorted(new.records - old.records)
    both = sorted(old.records & new.records)

    result = (
        "*******************************************************************\n"
        + "Records in original but not in new:\n\n"
        + "\n".join(old_only)
        + "\n\n"
        + "*******************************************************************\n"
        + "Records in new but not in original:\n\n"
        + "\n".join(new_only)
        + "\n\n"
        + "*******************************************************************\n"
        + f"records in original:    {len(old.records)}\n"
        f"  records in new:         {len(new.records)}\n"
        f"  records missing in new: {len(old_only)}\n"
        f"  records extra in new:   {len(new_only)}\n"
        + "*******************************************************************\n"
    )

    for record_str in both:
        # validate the fields are the same
        old_norm = normalize_float_records(old.fields[record_str])
        new_norm = normalize_float_records(new.fields[record_str])
        if old_norm != new_norm:
            old_ef = EpicsField()
            new_ef = EpicsField()
            for ef, norm in [(old_ef, old_norm), (new_ef, new_norm)]:
                for entry in norm:
                    name, _, value = entry.partition(" ")
                    ef.field_names.add(name)
                    ef.values[name] = value

            field_old_only = sorted(old_ef.field_names - new_ef.field_names)
            field_new_only = sorted(new_ef.field_names - old_ef.field_names)
            field_both = sorted(old_ef.field_names & new_ef.field_names)
            value_diffs = [
                f"{name} ('{old_ef.values[name]}' -> '{new_ef.values[name]}')"
                for name in field_both
                if old_ef.values[name] != new_ef.values[name]
            ]

            result += f"\nfields for '{record_str}' are different between the two DBs"
            if field_old_only:
                result += f"\n  only in original: {', '.join(field_old_only)}"
            if field_new_only:
                result += f"\n  only in new: {', '.join(field_new_only)}"
            if value_diffs:
                result += f"\n  different values: {', '.join(value_diffs)}"

    if not output:
        print(result)
    else:
        output.write_text(result + "\n")
