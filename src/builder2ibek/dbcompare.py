import re
from dataclasses import dataclass, field
from pathlib import Path

# extract record type, name and fields from an EPICS database file
regex_record = re.compile(
    r"(#)* *record *\( *([^,]*), *\"?([^\"]*)\"? *\)[\s\S]*?{([\s\S]*?)}"
)
# extract field name and value from the fields section of the above
regex_field = re.compile(r'(#)* *field *\( *([^,]*), *"?([^"]*)"? *\)')


@dataclass
class EpicsDb:
    path: Path
    text: str = ""
    records: set[str] = field(default_factory=lambda: set())
    fields: dict[str, set[str]] = field(default_factory=lambda: {})


def normalize_float_records(s: set[str]) -> set[str]:
    normalised = set()
    for item in s:
        try:
            parts = item.split(maxsplit=1)
            if len(parts) == 1:
                # blank fields are the same as absent fields
                continue
            name, value = parts
            # default values can be ignored
            if name == "SCAN" and value == "Passive":
                continue
            normalised.add(f"{name} {float(value)}")
        except (ValueError, IndexError):
            normalised.add(item)
    return normalised


def compare_dbs(
    old_path: Path, new_path: Path, ignore: list[str], output: Path | None = None
):
    """
    validate that two DBs have the same set of records

    used to ensure that an IOC converted to epics-containers has the same
    records as the original builder IOC
    """
    old = EpicsDb(old_path)
    new = EpicsDb(new_path)

    for db in [old, new]:
        db.text = db.path.read_text()
        for record in regex_record.finditer(db.text):
            if record.group(1) is not None:
                # skip commented out records
                continue
            rec_str = f"{record.group(2)} {record.group(3)}"
            # throw away duplicates in the old db
            if rec_str not in db.fields or db == new:
                db.records.add(rec_str)
                db.fields[rec_str] = set()
                for rec_field in regex_field.finditer(record.group(4)):
                    if rec_field.group(1) is not None:
                        # skip commented out fields
                        continue
                    db.fields[rec_str].add(f"{rec_field.group(2)} {rec_field.group(3)}")

    old_only = sorted(old.records - new.records)
    new_only = sorted(new.records - old.records)
    both = sorted(old.records & new.records)

    old_only_filtered = old_only.copy()
    new_only_filtered = new_only.copy()
    for filtered, unfiltered in [
        (old_only_filtered, old_only),
        (new_only_filtered, new_only),
    ]:
        for record_str in unfiltered:
            for s in ignore:
                if s in record_str:
                    filtered.remove(record_str)

    result = (
        "*******************************************************************\n"
        + "Records in original but not in new:\n\n"
        + "\n".join(old_only_filtered)
        + "\n\n"
        + "*******************************************************************\n"
        + "Records in new but not in original:\n\n"
        + "\n".join(new_only_filtered)
        + "\n\n"
        + "*******************************************************************\n"
        + f"records in original:    {len(old.records)}\n"
        f"  records in new:         {len(new.records)}\n"
        f"  records missing in new: {len(old_only_filtered)}\n"
        f"  records extra in new:   {len(new_only_filtered)}\n"
        + "*******************************************************************\n"
    )

    for record_str in both:
        # validate the fields are the same
        old_norm = normalize_float_records(old.fields[record_str])
        new_norm = normalize_float_records(new.fields[record_str])
        if old_norm != new_norm:
            result += f"\nfields for '{record_str}' are different between the two DBs"

    if not output:
        print(result)
    else:
        output.write_text(result + "\n")
