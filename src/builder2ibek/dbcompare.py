import re
from dataclasses import dataclass, field
from pathlib import Path

# https://regex101.com/r/M5dmVh/1
# extract record name, type, and fields from an EPICS database file
regex_record = re.compile(r'record *\( *([^,]*), *"?([^"]*)"? *\)[\s\S]*?{([\s\S]*?)}')
regex_field = re.compile(r'field *\( *([^,]*), *"?([^"]*)"? *\)')


@dataclass
class EpicsDb:
    path: Path
    text: str = ""
    records: set[str] = field(default_factory=lambda: set())
    fields: dict[str, set[str]] = field(default_factory=lambda: {})


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
            db.records.add(f"{record.group(1)} {record.group(2)}")
            db.fields[record.group(2)] = set()
            for rec_field in regex_field.finditer(record.group(3)):
                db.fields[record.group(2)].add(
                    f"{rec_field.group(1)} {rec_field.group(2)}"
                )

    old_only = sorted(old.records - new.records)
    new_only = sorted(new.records - old.records)

    old_only_filtered = old_only.copy()
    new_only_filtered = new_only.copy()
    for filtered, unfiltered in [
        (old_only_filtered, old_only),
        (new_only_filtered, new_only),
    ]:
        for record in unfiltered:
            for s in ignore:
                if s in record:
                    filtered.remove(record)

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
    )
    if not output:
        print(result)
    else:
        output.write_text(result)