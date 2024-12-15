import re
from pathlib import Path

regex_record = re.compile(r'record *\( *([^,]*), *"?([^"]*)"? *\)[\s\S]{')


def compare_dbs(original: Path, new: Path):
    """
    validate that two DBs have the same set of records

    used to ensure that an IOC converted to epics-containers has the same
    records as the original builder IOC
    """
    old_text = original.read_text()
    new_text = new.read_text()

    old_set = set()
    for record in regex_record.finditer(old_text):
        old_set.add(f"{record.group(1)} {record.group(2)}")
    new_set = set()
    for record in regex_record.finditer(new_text):
        new_set.add(f"{record.group(1)} {record.group(2)}")

    old_only = sorted(old_set - new_set)
    new_only = sorted(new_set - old_set)
    print("\n*****************************************************************")
    print("Records in original but not in new:")
    print("\n".join(old_only))
    print("\n*****************************************************************")
    print("Records in new but not in original:")
    print("\n".join(new_only))
    print("\n*****************************************************************")
    print("  records in original:    ", len(old_set))
    print("  records in new:         ", len(new_set))
    print("  records missing in new: ", len(old_only))
    print("  records extra in new:   ", len(new_only))
