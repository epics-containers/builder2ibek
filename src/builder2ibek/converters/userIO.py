"""
The convertor for the userIO support module

builder's userIO classes are AutoSubstitutions: each loads one template of the
module with its XML attributes as the macros. This converter expands that
template itself, from the copies of userIO 2-32's templates in userIO_db/, and
writes the records to records.db with the raw records (see records.py), so the
IOC needs no userIO in its image. A record with a ``#% autosave <pass>
<fields>`` tag gets an autosave info tag naming those fields.
"""

import re
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "userIO"

TEMPLATES = Path(__file__).parent / "userIO_db"

# builder's simulation classes load their parent's template, with the I/O link
# emptied and soft device support
SIMULATIONS = {"ai_sim": "INP", "ao_sim": "OUT", "bi_sim": "INP", "bo_sim": "OUT"}

# templates loaded by a class of another name
TEMPLATE_FILES = {"caLab_interface": "caLab_interface.db"}

# $(name), $(name=default) or ${...}; after a comma come scoped macro
# definitions, as in $(dom,undefined), which these templates do not use
MACRO = re.compile(r"\$[({]([A-Za-z0-9_]+)(?:=([^),}]*))?(?:,[^)}]*)?[)}]")
RECORD = re.compile(
    r'(?:g?record)\(\s*([A-Za-z0-9_]+)\s*,\s*"([^"]*)"\s*\)\s*\{(.*?)\n\s*\}',
    re.S,
)
ITEM = re.compile(r'\b(field|info)\(\s*([A-Za-z0-9_:]+)\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)')
AUTOSAVE = re.compile(r"^#\s*%\s*autosave\s+(\d+)\s*(.*)$", re.M)


def expand(text: str, macros: dict[str, str]) -> tuple[str, set[str]]:
    """The template text with its macros replaced, as msi does: a macro with
    no value takes its default, without the quotes around a quoted one.
    Returns the text and the macros that had neither, which become empty."""
    missing: set[str] = set()

    def value(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        if name in macros:
            return macros[name]
        if default is not None:
            if len(default) > 1 and default[0] == default[-1] == '"':
                default = default[1:-1]
            return MACRO.sub(value, default)
        missing.add(name)
        return ""

    return MACRO.sub(value, text), missing


def records(
    text: str,
) -> list[tuple[str, str, dict[str, str], dict[str, str]]]:
    """Each record of an expanded template: its type, name, fields and info
    tags, an autosave tag before it becoming autosaveFields (pass 1) or
    autosaveFields_pass<n>."""
    found = []
    start = 0
    for match in RECORD.finditer(text):
        fields: dict[str, str] = {}
        infos: dict[str, str] = {}
        tags = list(AUTOSAVE.finditer(text, start, match.start()))
        if tags and tags[-1].group(2).split():
            pass_number = tags[-1].group(1)
            key = (
                "autosaveFields"
                if pass_number == "1"
                else (f"autosaveFields_pass{pass_number}")
            )
            infos[key] = " ".join(tags[-1].group(2).split())
        body = "\n".join(
            line
            for line in match.group(3).splitlines()
            if not line.strip().startswith("#")
        )
        for kind, key, val in ITEM.findall(body):
            (fields if kind == "field" else infos)[key] = val
        found.append((match.group(1), match.group(2), fields, infos))
        start = match.end()
    return found


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the userIO support module:
    the entity's template goes to records.db as raw records, see the module
    docstring
    """
    base = entity_type.removeprefix("auto_")
    base = base.removesuffix("_sim") if entity_type in SIMULATIONS else base
    template = TEMPLATES / TEMPLATE_FILES.get(base, f"{base}.template")
    if not template.is_file():
        # no template to expand: the entity stays for its ibek model
        entity.remove("name")
        return

    macros = dict(entity.xml_attributes())
    if entity_type in SIMULATIONS:
        macros[SIMULATIONS[entity_type]] = ""
        macros["DTYP"] = "Soft Channel"
    # comments other than autosave tags carry only GUI and GDA macros
    lines = template.read_text().splitlines()
    kept = [x for x in lines if not x.lstrip().startswith("#") or AUTOSAVE.match(x)]
    text, missing = expand("\n".join(kept), macros)
    if missing:
        ioc.extra_warnings.append(
            f"{Path(ioc.source_file).stem}: userIO.{entity_type} "
            f"{macros.get('P', '')}{macros.get('R', '')} sets no "
            f"{', '.join(sorted(missing))}, which {template.name} needs: "
            f"left empty in {template.name}'s records"
        )
    for record_type, name, fields, infos in records(text):
        # a record loaded again takes the later fields, as dbLoadRecords does
        _, known = ioc.raw_records.get(name, (record_type, {}))
        ioc.raw_records[name] = (record_type, {**known, **fields})
        if infos:
            ioc.raw_record_info.setdefault(name, {}).update(infos)
    entity.delete_me()
