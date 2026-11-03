"""Where the tool reads and writes, and what differs from one site to another.

One object, `CFG`, set once by the command line (see `pvi_from_edm.py`) and handed to
each worker process of a sweep. Nothing in the tool knows a path or a module by name.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _paths(*names: str) -> list[Path]:
    return [Path(n) for n in names]


@dataclass
class Settings:
    # support repo folders, key -> folder; `repo:` in an override names a key
    repos: dict[str, Path] = field(default_factory=dict)
    # keys of repos whose device files must match hygiene_pattern nowhere
    public_repos: set[str] = field(default_factory=set)
    hygiene_pattern: str = ""

    # release roots, in order of preference
    prod: list[Path] = field(default_factory=lambda: _paths("/dls_sw/prod/R3.14.12.7/support", "/dls_sw/prod/R7.0.7/support"))
    work: list[Path] = field(default_factory=lambda: _paths("/dls_sw/work/R3.14.12.7/support", "/dls_sw/work/R7.0.7/support"))
    older: list[Path] = field(default_factory=lambda: [Path(f"/dls_sw/prod/{v}/support") for v in ("R3.14.12.6", "R3.14.12.3", "R3.14.12.2", "R3.14.12.1", "R3.14.11", "R3.14.8.2")])
    # included by bare name, with any RELEASE dependency hidden in files a release does not ship
    last_resort_modules: list[str] = field(default_factory=lambda: ["ADCore", "asyn"])
    # folder name -> the name its releases go by
    release_aliases: dict[str, str] = field(default_factory=dict)
    msi: Path = Path("/dls_sw/epics/R7.0.7/base/bin/linux-x86_64/msi")
    base_dbd: Path = Path("/dls_sw/epics/R7.0.7/base/dbd")
    support_dbd_glob: str = "/dls_sw/prod/R3.14.12.7/support/*/*/dbd/{}Record.dbd"
    edm_colors: Path | None = None

    # data the tool reads
    classification: Path | None = None
    classify_rules: Path | None = None
    overrides: Path | None = None
    collisions: Path | None = None

    # folders the tool writes
    output: Path = Path("pvi-from-edm-work/out")
    sandbox: Path = Path("pvi-from-edm-work/sandbox")
    review: Path = Path("pvi-from-edm-work/review")
    status: Path = Path("pvi-from-edm-work")

    # folders written by hand: a sweep never touches them; (repo key, folder)
    hand_written: set[tuple[str, str]] = field(default_factory=set)
    # a forked module, generated once and installed in both: (repo, folder) -> (repo, folder)
    forks: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    # device file names another folder may not take: (stem, repo key, folder)
    reserved_stems: list[tuple[str, str, str]] = field(default_factory=list)
    # screens that leave a copied offLabel on buttons whose onLabel says what they do
    held_label_screens: set[str] = field(default_factory=set)

    def msi_path(self) -> Path | None:
        """The configured msi, or the one on PATH."""
        if self.msi.exists():
            return self.msi
        found = shutil.which("msi")
        return Path(found) if found else None

    def fork_twins(self) -> dict[tuple[str, str], tuple[str, str]]:
        return {v: k for k, v in self.forks.items()}


CFG = Settings()


def install(new: Settings) -> None:
    """Make `new` the settings of this process: modules hold a reference to CFG."""
    if new is not CFG:
        CFG.__dict__.clear()
        CFG.__dict__.update(new.__dict__)


PATH_KEYS = {"msi": "msi", "base_dbd": "base_dbd", "edm_colors": "edm_colors", "classification": "classification", "classify_rules": "classify_rules", "overrides": "overrides", "collisions": "collisions"}
PATH_LIST_KEYS = {"prod_roots": "prod", "work_roots": "work", "older_roots": "older"}
PLAIN_KEYS = {"hygiene_pattern", "last_resort_modules", "release_aliases", "support_dbd_glob"}


def from_file(path: Path) -> Settings:
    """Settings from a YAML file. A relative path in it is relative to the file."""
    raw = yaml.safe_load(path.read_text()) or {}
    known = {"repos", "public_repos", "hand_written", "forks", "reserved_stems", "held_label_screens", *PATH_KEYS, *PATH_LIST_KEYS, *PLAIN_KEYS}
    if unknown := sorted(set(raw) - known):
        raise ValueError(f"{path}: unknown settings: {', '.join(unknown)}")
    base = path.resolve().parent
    s = Settings()
    for k, attr in PATH_KEYS.items():
        if raw.get(k):
            setattr(s, attr, base / raw[k])
    for k, attr in PATH_LIST_KEYS.items():
        if k in raw:
            setattr(s, attr, [base / p for p in raw[k] or []])
    for k in PLAIN_KEYS:
        if k in raw:
            setattr(s, k, raw[k])
    s.repos = {k: base / v for k, v in (raw.get("repos") or {}).items()}
    s.public_repos = set(raw.get("public_repos") or [])
    s.hand_written = {(e["repo"], e["folder"]) for e in raw.get("hand_written") or []}
    s.forks = {(e["repo"], e["folder"]): (e["twin_repo"], e["twin_folder"]) for e in raw.get("forks") or []}
    s.reserved_stems = [(e["stem"], e["repo"], e["folder"]) for e in raw.get("reserved_stems") or []]
    s.held_label_screens = set(raw.get("held_label_screens") or [])
    if s.support_dbd_glob.count("{}") != 1:
        raise ValueError(f"{path}: support_dbd_glob needs one {{}} for the record type")
    return s
