import re
from pathlib import Path

regex_autosave = [
    re.compile(rf'# *% *autosave *{n} *(.*)[\s\S]*?record *\(.*, *"?([^"]*)"?\)')
    for n in range(3)
]


def write_req_file(f: Path, record_set: set[str]):
    """
    Write an autosave request file, one PV per line.

    Each record_set entry is "recordname [FIELD ...]": the record name followed
    by the fields listed on its `#% autosave` comment. autosave's readReqFile()
    parses a line with `sscanf(line, "%s", name)`, so it takes only the first
    whitespace delimited token and silently discards the rest -- a line holding
    several fields saves the record's .VAL and nothing else. Each field
    therefore needs its own `recordname.FIELD` line.

    VAL is written as the bare record name: the same PV, and the spelling
    migrate_autosave uses in the .sav files.
    """
    print(f"writing file {f}")

    lines: set[str] = set()
    for entry in record_set:
        record, *fields = entry.split() or [""]
        if not record:
            continue
        if not fields:
            lines.add(record)
        for field in fields:
            lines.add(record if field == "VAL" else f"{record}.{field}")

    f.write_text("\n".join(sorted(lines)) + "\n")


def parse_templates(out_folder: Path, db_list: list[Path]):
    """
    DLS has 3 autosave levels
        0 = save on pass 0
        1 = save on pass 0 and 1
        2 = save on pass 1 only

    Areadetector and other support modules use:
        template_name_positions.req for save on pass 0
        template_name_settings.req for save on pass 0 and pass 1
        the autosave docs seem to back the idea that pass 1 only is never used

    So this translation will make
        0 => template_name_positions.req
        1 => template_name_settings.req
    """
    for db in db_list:
        text = db.read_text()

        positions: set[str] = set()
        settings: set[str] = set()
        this_set: set = set()
        for n in range(3):
            match n:
                case 0:
                    this_set = positions
                case 1 | 2:
                    this_set = settings
            for result in regex_autosave[n].finditer(text):
                this_set.add(f"{result.group(2)} {result.group(1)}")

        if positions:
            req_file = out_folder / f"{db.stem}_positions.req"
            write_req_file(req_file, positions)
        if settings:
            req_file = out_folder / f"{db.stem}_settings.req"
            write_req_file(req_file, settings)
