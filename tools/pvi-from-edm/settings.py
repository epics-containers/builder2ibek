"""Where the tool reads and writes, and what differs from one site to another.

One object, `CFG`, set once by the command line (see `pvi_from_edm.py`) and handed to
each worker process of a sweep. Nothing in the tool knows a path or a module by name:
a site gives them on the command line or in its settings file.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Settings:
    # support repo folders, key -> folder; `repo:` in an override names a key
    repos: dict[str, Path] = field(default_factory=dict)
    # keys of repos whose device files must match hygiene_pattern nowhere
    public_repos: set[str] = field(default_factory=set)
    hygiene_pattern: str = ""

    # release roots, in order of preference
    prod: list[Path] = field(default_factory=list)
    work: list[Path] = field(default_factory=list)
    older: list[Path] = field(default_factory=list)
    # included by bare name, with any RELEASE dependency hidden in files a release does not ship
    last_resort_modules: list[str] = field(default_factory=list)
    # folder name -> the name its releases go by
    release_aliases: dict[str, str] = field(default_factory=dict)
    msi: Path | None = None
    base_dbd: Path | None = None
    support_dbd_glob: str = ""
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

    # what a run may lose and still exit 0: (folder, entity, or "" for the module) -> why
    expected_losses: dict[tuple[str, str], str] = field(default_factory=dict)
    # version differences seen and accepted: (folder, install.yml's version, what was validated) -> why
    accepted_versions: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # (folder, substitutions file) -> why msi may refuse it
    accepted_msi_refusals: dict[tuple[str, str], str] = field(default_factory=dict)
    # values of `version` in an install.yml that name no release
    install_placeholders: set[str] = field(default_factory=set)

    def msi_path(self) -> Path | None:
        """The configured msi, or the one on PATH."""
        if self.msi and self.msi.exists():
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
    known = {"repos", "public_repos", "hand_written", "forks", "reserved_stems", "held_label_screens", "expected_losses", "accepted_versions", "accepted_msi_refusals", "install_placeholders", *PATH_KEYS, *PATH_LIST_KEYS, *PLAIN_KEYS}
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
    s.install_placeholders = set(raw.get("install_placeholders") or [])

    def with_reason(key: str) -> list[dict]:
        entries = raw.get(key) or []
        for e in entries:
            if not e.get("reason"):
                raise ValueError(f"{path}: an entry of {key} has no reason: {e}")
        return entries

    s.expected_losses = {(e["folder"], e.get("entity", "")): e["reason"] for e in with_reason("expected_losses")}
    s.accepted_versions = {(e["folder"], str(e["install"]), str(e["validated"])): e["reason"] for e in with_reason("accepted_versions")}
    s.accepted_msi_refusals = {(e["folder"], e["file"]): e["reason"] for e in with_reason("accepted_msi_refusals")}
    if s.support_dbd_glob and s.support_dbd_glob.count("{}") != 1:
        raise ValueError(f"{path}: support_dbd_glob needs one {{}} for the record type")
    return s
