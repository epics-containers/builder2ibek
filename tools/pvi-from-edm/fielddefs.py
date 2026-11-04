"""Which fields a record type has, from the `recordtype` blocks of .dbd files: EPICS
base, the module's release and its dependencies, then any support module."""

from __future__ import annotations

import glob
import re
from functools import lru_cache
from pathlib import Path

from release import deps
from settings import CFG
RECORDTYPE = re.compile(r"recordtype\s*\(\s*(\w+)\s*\)\s*\{(.*?)^\}", re.S | re.M)
FIELD = re.compile(r"field\s*\(\s*(\w+)\s*,\s*(DBF_\w+)\s*\)")
ALARM_FIELDS = {"SEVR", "STAT", "NSEV", "NSTA", "AMSG", "NAMSG", "ACKS", "ACKT"}
STRINGISH = {"DBF_STRING", "DBF_INLINK", "DBF_OUTLINK", "DBF_FWDLINK", "DBF_NOACCESS"}


def parse_dbd(text: str) -> dict[str, dict[str, str]]:
    return {m.group(1): dict(FIELD.findall(m.group(2))) for m in RECORDTYPE.finditer(text)}


@lru_cache(maxsize=None)
def _common() -> dict[str, str]:
    f = CFG.base_dbd / "dbCommon.dbd" if CFG.base_dbd else None
    return dict(FIELD.findall(f.read_text(errors="replace"))) if f and f.exists() else {}


@lru_cache(maxsize=None)
def _file(path: str) -> dict[str, dict[str, str]]:
    return parse_dbd(Path(path).read_text(errors="replace"))


@lru_cache(maxsize=None)
def _anywhere(rtype: str) -> dict[str, str] | None:
    """The newest release holding this record type, for types no dependency declares."""
    if not CFG.support_dbd_glob:
        return None
    # file names don't always match the type's case: sCalcoutRecord.dbd holds scalcout
    any_case = "".join(f"[{c.lower()}{c.upper()}]" for c in rtype)
    for f in sorted(glob.glob(CFG.support_dbd_glob.format(any_case)), reverse=True):
        if rtype in (found := _file(f)):
            return found[rtype]
    return None


@lru_cache(maxsize=None)
def fields_of(rtype: str, release: Path) -> dict[str, str] | None:
    """Field name -> DBF type for a record type, or None if no definition is found."""
    base = CFG.base_dbd / f"{rtype}Record.dbd" if CFG.base_dbd else None
    if base and base.exists() and rtype in (found := _file(str(base))):
        return {**_common(), **found[rtype]}
    for rel in [release, *(d for _, d in deps(release))]:
        p = rel / "dbd" / f"{rtype}Record.dbd"
        if p.exists() and rtype in (found := _file(str(p))):
            return {**_common(), **found[rtype]}
    found = _anywhere(rtype)
    return {**_common(), **found} if found else None


def field_type(rtype: str, field: str, release: Path) -> str | None:
    defs = fields_of(rtype, release)
    return defs.get(field.rstrip("$")) if defs else None


def left_out_why(rtype: str, field: str, release: Path) -> str:
    """Why a field shown on a screen stays out of the PVI; empty if it goes in."""
    name = field.rstrip("$")
    if name in ALARM_FIELDS:
        return "alarm field"
    defs = fields_of(rtype, release)
    if defs is None:
        return f"no definition found for record type {rtype}"
    return "" if name in defs else f"not a field of {rtype}"
