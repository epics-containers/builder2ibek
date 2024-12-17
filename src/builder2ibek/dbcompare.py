import re
from pathlib import Path

regex_record = re.compile(r'record *\( *([^,]*), *"?([^"]*)"? *\)[\s\S]{')


def compare_dbs(
    original: Path, new: Path, ignore: list[str], output: Path | None = None
):
    """
    validate that two DBs have the same set of records

    used to ensure that an IOC converted to epics-containers has the same
    records as the original builder IOC
    """
    old_text = original.read_text()
    new_text = new.read_text()

    old_set: set[str] = set()
    for record in regex_record.finditer(old_text):
        old_set.add(f"{record.group(1)} {record.group(2)}")
    new_set: set[str] = set()
    for record in regex_record.finditer(new_text):
        new_set.add(f"{record.group(1)} {record.group(2)}")

    old_only = sorted(old_set - new_set)
    new_only = sorted(new_set - old_set)

    old_only_filtered = old_only.copy()
    new_only_filtered = new_only.copy()
    for rec in old_only:
        for s in ignore:
            if s in rec:
                old_only_filtered.remove(rec)
    for rec in new_only:
        for s in ignore:
            if s in rec:
                new_only_filtered.remove(rec)

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
        + f"records in original:    {len(old_set)}\n"
        f"  records in new:         {len(new_set)}\n"
        f"  records missing in new: {len(old_only_filtered)}\n"
        f"  records extra in new:   {len(new_only_filtered)}\n"
    )
    if not output:
        print(result)
    else:
        output.write_text(result)
