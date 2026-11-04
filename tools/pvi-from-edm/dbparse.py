"""Expand a released EPICS database file into its true record list.

The released db/ file is the source of truth for macros. It may still hold
`substitute` + `include` (msi syntax), which are expanded here as msi would.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REC = re.compile(r'''^\s*g?record\s*\(\s*(\w+)\s*,\s*(?:"([^"]+)"|([^"\s]+))\s*\)\s*(\{)?''')
FIELD = re.compile(r'^\s*field\s*\(\s*(\w+)\s*,\s*"?(.*?)"?\s*\)\s*(?:#.*)?$')
SUBST = re.compile(r'^\s*substitute\s+"([^"]*)"')
INCL = re.compile(r'^\s*include\s+"([^"]+)"')
GUI = re.compile(r"^#\s*%\s*gui\s*,\s*([^,]*),\s*(edm|edmtab|edmembed)\s*,\s*([^,]+?)\s*(?:,(.*))?$")
MACRO_DEF = re.compile(r"\$\((\w+)=([^)]*)\)")
MACRO_ANY = re.compile(r"\$\((\w+)(?:=[^)]*)?\)")

INPUT = {"ai", "bi", "mbbi", "mbbiDirect", "longin", "stringin", "int64in", "lsi", "calc", "event", "histogram", "scalcin", "sel", "compress"}
OUTPUT = {"ao", "bo", "mbbo", "mbboDirect", "longout", "stringout", "int64out", "lso", "calcout", "scalcout"}


@dataclass
class Record:
    rtype: str
    name: str
    fields: dict = field(default_factory=dict)
    file: str = ""


@dataclass
class Db:
    path: Path
    records: dict[str, Record] = field(default_factory=dict)
    gui: list[tuple[str, dict]] = field(default_factory=list)  # (edl, macro map)
    gui_embed: list[tuple[str, dict]] = field(default_factory=list)  # edmembed tags
    includes: list[str] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)  # macro -> default in a record name


def _strip_defaults(s: str) -> str:
    """$(a=b) to $(a): record names are compared with macros only."""
    return MACRO_DEF.sub(lambda m: f"$({m.group(1)})", s)


def _subst(s: str, env: dict) -> str:
    def rep(m):
        return env.get(m.group(1), m.group(0))

    return MACRO_ANY.sub(rep, s)


def gui_file(raw: str) -> str:
    """`x.edl`, `EDM_FILE=x.edl` and `$(EDM_FILE=x.edl)` all name the screen x.edl."""
    s = raw.strip()
    if m := re.fullmatch(r"\$\(\w+=([^)]*)\)", s):
        s = m.group(1)
    if m := re.fullmatch(r"\w+=(.*)", s):
        s = m.group(1)
    return s.strip()


def parse_db(path: Path, env: dict | None = None, db: Db | None = None, search: list[Path] | None = None) -> Db:
    path = Path(path)
    env = dict(env or {})
    db = db or Db(path=path)
    cur: Record | None = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.replace(",undefined)", ")")  # msi's mark on an already compiled db
        if m := GUI.match(line):
            macros = {}
            for part in (m.group(4) or "").split(","):
                if "=" in part:
                    k, _, v = part.partition("=")
                    macros[k.strip()] = _strip_defaults(v.strip())
            entry = (gui_file(m.group(3)), macros)
            (db.gui_embed if m.group(2) == "edmembed" else db.gui).append(entry)
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if m := SUBST.match(line):
            for part in m.group(1).split(","):
                k, _, v = part.partition("=")
                env[k.strip()] = v.strip()
            continue
        if m := INCL.match(line):
            db.includes.append(m.group(1))
            where = [path.parent, *(search or [])]
            hit = next((d / m.group(1) for d in where if (d / m.group(1)).is_file()), None)
            if hit is None:
                db.missing_includes.append(m.group(1))
            else:
                parse_db(hit, env, db, search)
            continue
        if cur is None and (m := REC.match(line)):
            for k, v in MACRO_DEF.findall(m.group(2) or m.group(3)):
                db.defaults.setdefault(k, v)
            name = _subst(_strip_defaults(m.group(2) or m.group(3)), env)
            cur = Record(rtype=m.group(1), name=name, file=path.name)
            # a later record of the same name overlays and may change nothing else
            if name in db.records:
                db.records[name].fields.update({})
                cur = db.records[name]
            else:
                db.records[name] = cur
            if "}" in line:
                cur = None
            continue
        if cur is not None:
            if m := FIELD.match(line):
                cur.fields[m.group(1)] = _subst(m.group(2), env)
            if s.endswith("}") or s == "}":
                cur = None
    return db


def macros_in(s: str) -> list[str]:
    return [m.group(1) for m in MACRO_ANY.finditer(s)]


def static_suffix(pv: str) -> str:
    """The name with any leading run of macros removed: `$(P)$(R):ID` to `:ID`."""
    return re.sub(r"^(?:\$\(\w+\))+", "", pv)


def default_of(value: str) -> str:
    """Field value with `$(m=default)` replaced by the default, for labels."""
    out = MACRO_DEF.sub(lambda m: m.group(2), value)
    return out
