"""Find the DLS release a support module's screens and databases come from."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from settings import CFG  # noqa: E402

VERSION = re.compile(r"^(dls)?\d")


def vkey(v: str) -> list:
    """Sort key: numeric parts compare as numbers, others sort below them."""
    return [(1, int(x), "") if x.isdigit() else (0, 0, x) for x in re.split(r"[-._]", v)]


def versions(tree: Path, name: str) -> list[str]:
    p = tree / name
    if not p.is_dir():
        return []
    return sorted((d.name for d in p.iterdir() if d.is_dir() and VERSION.match(d.name)), key=vkey)


def has_screens(rel: Path) -> bool:
    return any(rel.glob("data/*.edl")) or any(rel.glob("*App/opi/edl/*.edl"))


def names_for(folder: str, module: str, install: dict) -> list[str]:
    raw = [folder, module, str(install.get("module", ""))]
    raw += [re.sub(r"[-_]dls$", "", n) for n in raw]
    raw += [CFG.release_aliases.get(n, n) for n in raw]
    out: list[str] = []
    for n in raw:
        if n and n not in out:
            out.append(n)
    return out


def candidates(folder: str, module: str, install: dict) -> list[tuple[Path, str]]:
    """Releases in order of preference, each with how it was chosen."""
    names = names_for(folder, module, install)
    want = str(install.get("version", ""))
    base = re.sub(r"(ec\d*|-epics-containers\d*)$", "", want)
    out: list[tuple[Path, str]] = []
    for tree in CFG.prod:
        for n in names:
            vs = versions(tree, n)
            if want in vs:
                out.append((tree / n / want, f"exact ({tree.parent.name})"))
            elif base and base in vs:
                out.append((tree / n / base, f"ec suffix stripped ({tree.parent.name})"))
    for tree in CFG.prod:
        for n in names:
            vs = versions(tree, n)
            if vs:
                out.append((tree / n / vs[-1], f"newest in {tree.parent.name}; install.yml says {want}"))
    for tree in CFG.work:
        for n in names:
            p = tree / n
            if (p / "db").is_dir() or (p / "data").is_dir():
                out.append((p, f"unreleased {tree.parent.parent.name}/{tree.parent.name}; install.yml says {want}"))
    for tree in CFG.older:
        for n in names:
            vs = versions(tree, n)
            if vs:
                out.append((tree / n / vs[-1], f"newest in {tree.parent.name}; install.yml says {want}"))
    return out


def pick(folder: str, module: str, install: dict) -> tuple[Path | None, str]:
    """First candidate that has screens, otherwise the first candidate."""
    cands = candidates(folder, module, install)
    if not cands:
        return None, "no release in any tree"
    for rel, how in cands:
        if has_screens(rel):
            return rel, how
    return cands[0]


ASSIGN = re.compile(r"^\s*(\w+)\s*=\s*(\S+)\s*(?:#.*)?$")
SKIP_DEPS = {"TEMPLATE_TOP", "EPICS_BASE", "EPICS_EXTENSIONS", "PMAC_CONFIG", "WORK"}


@lru_cache(maxsize=None)
def deps(rel: Path, depth: int = 2) -> tuple[tuple[str, Path], ...]:
    """configure/RELEASE dependencies as (macro, path), following `depth` levels."""
    env: dict[str, str] = {"TOP": str(rel)}
    out: list[tuple[str, Path]] = []
    cfg = rel / "configure"

    def sub(v: str) -> str:
        return re.sub(r"\$[({](\w+)[)}]", lambda x: env.get(x.group(1), x.group(0)), v)

    def read(f: Path, seen: set):
        if f in seen or not f.is_file():
            return
        seen.add(f)
        for line in f.read_text(errors="replace").splitlines():
            if inc := re.match(r"^\s*-?include\s+(\S+)", line):
                read(Path(sub(inc.group(1))), seen)
                continue
            if not (m := ASSIGN.match(line)):
                continue
            k, v = m.group(1), sub(m.group(2))
            env[k] = v
            if k in SKIP_DEPS or "$" in v or not v.startswith("/"):
                continue
            p = Path(v)
            if (p / "db").is_dir() or (p / "data").is_dir():
                out.append((k, p))

    seen: set = set()
    for f in [cfg / "RELEASE", cfg / "RELEASE.local", *sorted(cfg.glob("RELEASE.*Common*"))] if cfg.is_dir() else []:
        read(f, seen)
    if depth > 1:
        for _, p in list(out):
            for k, q in deps(p, depth - 1):
                if all(q != o for _, o in out):
                    out.append((k, q))
    return tuple(out)


def db_search_path(rel: Path, extra: list[Path] | None = None) -> list[Path]:
    dirs = [rel / "db", *sorted(rel.glob("*App/Db"))] + [p / "db" for _, p in deps(rel)] + list(extra or []) + last_resort()
    return [d for d in dirs if d.is_dir()]


def last_resort() -> list[Path]:
    """Templates included by bare name, with any RELEASE dependency hidden in files a
    release does not ship: the newest releases of these modules answer those."""
    out = []
    for n in CFG.last_resort_modules:
        vs = versions(CFG.prod[0], n) if CFG.prod else []
        if vs:
            out.append(CFG.prod[0] / n / vs[-1] / "db")
    return out


def find_db(rel: Path, file: str, extra: list[Path] | None = None) -> Path | None:
    """A database line such as `$(MOD)/db/x.template` to the file holding it."""
    name = file.rsplit("/", 1)[-1]
    for d in db_search_path(rel, extra):
        if (d / name).is_file():
            return d / name
    return None
