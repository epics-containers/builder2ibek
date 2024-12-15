import re
from pathlib import Path

regex_record = [
    re.compile(rf'# *% *autosave *{n} *(.*)[\s\S]*?record *\(.*, *"?([^"]*)"?\)')
    for n in range(3)
]


def compare_dbs(original: Path, new: Path):
    """
    validate that two DBs have the same set of records

    used to ensure that an IOC converted to epics-containers has the same
    records as the original builder IOC
    """
    pass
