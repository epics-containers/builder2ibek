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

    print("*******************************************************************")
    print("Records in original but not in new:")
    print("\n".join(sorted(old_set - new_set)))
    print("*******************************************************************")
    print("Records in new but not in original:")
    print("\n".join(sorted(new_set - old_set)))
