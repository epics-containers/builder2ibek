"""
Index of the runtime patterns builder2ibek can use in place of compiled support.

A runtime pattern is a support module whose files (``*.ibek.support.yaml``, protocol,
template) are vendored into an IOC instance with ``ibek pattern add``, so the IOC
runs on a stock image instead of one with the module compiled in. The patterns come
from the two libraries ibek knows by default, which this repo pins as submodules at
the release tags in :data:`LIBRARY_VERSIONS`. The index is read from those
checkouts, or, where they are absent (an installed builder2ibek), from a shallow
clone of each library at its tag in the user's cache. Every library folder holding
``<folder>/<folder>.ibek.support.yaml`` is a pattern for the module of that name, and
the support YAML lists its entity models.

:meth:`PatternIndex.plan` decides, for one converted IOC, which modules could come
from a pattern. A module goes to its pattern when:

- it is not listed in :data:`GENERIC_DIFFERS`. Those modules also have a generic
  model in ``ibek-support*`` that their pattern does not match, so an entity valid
  for one is not the same device for the other;
- every one of the IOC's entities of that module validates against the pattern
  model. A module is vendored whole or not at all, so one entity the pattern
  rejects keeps the whole module build-time.

Any other module stays build-time, so it needs an image with the module compiled
in, and the plan says why. Which modules a given image already builds is not known
here, so a plan says what could come from a pattern, not what must.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ibek.entity_factory import EntityFactory
from ibek.ioc import clear_entity_model_ids
from ibek.ioc_factory import IocFactory
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES
from pydantic import ValidationError
from pydantic.warnings import PydanticDeprecatedSince211
from ruamel.yaml import YAML

_project_root = Path(__file__).parent.parent.parent

# The pattern libraries, in the order ibek probes an unqualified pattern name. Each is
# a submodule at the repo root, named as ibek names it in its library registry.
LIBRARIES = ("ibek-runtime-streamdevice", "ibek-runtime-support")

# The release tag each library submodule is pinned at, for an installed
# builder2ibek, which has no submodules to read it from. tests/test_patterns.py
# checks it against the submodules, so a pin bump updates it too.
LIBRARY_VERSIONS: dict[str, str] = {
    "ibek-runtime-streamdevice": "0.7.3",
    "ibek-runtime-support": "0.3.1",
}

# Modules that have both a pattern and a generic model in ibek-support* are listed
# in exactly one of these two tables; tests/test_patterns.py checks that against the
# submodules, and checks each entry by comparing the two models. The tables are
# written out rather than worked out from ibek-support*, so that the decision does
# not depend on which support YAMLs a checkout has (CI has only a vendored subset of
# ibek-support-dls).

# The pattern model accepts everything the generic model does, to the same effect.
# plan() needs only GENERIC_DIFFERS; this table records the other half of the
# decision so that the tests can check it.
ALIGNED: frozenset[str] = frozenset(
    {
        "CrateMonitor",
        "ETLdetector",
        "GR150",
        "cognexDataMan100",
        "enzLoCuM4",
        "oxCryo",
        "strainGauge",
    }
)

# The pattern model differs from the generic one: a model or parameter is missing or
# renamed, a type or default changed. The module stays build-time until its pattern
# is aligned with the generic model, and aligning one means moving it to ALIGNED.
GENERIC_DIFFERS: frozenset[str] = frozenset(
    {
        "OxInstCryojet",
        "QPC",
        "SycosH-Hot",
        "agilent33220A",
        "agilent53220",
        "alicatGasFlow",
        "currAmp",
        "digitelMpc",
        "eurotherm2k",
        "fw102",
        "harvardSyringe",
        "keithley6514",
        "lakeshore340",
        "laudaRE2xx",
        "leybold",
        "linkam",
        "mks937a",
        "mks937b",
        "motomanNX100",
    }
)


class PatternIndexError(Exception):
    """The pattern libraries cannot be read."""


@dataclass(frozen=True)
class Pattern:
    """One pattern folder in a library at its pinned tag."""

    library: str
    module: str
    version: str
    models: frozenset[str]
    support_yaml: Path

    @property
    def library_path(self) -> Path:
        """The local copy of the library, at ``version``, to vendor from."""
        return self.support_yaml.parent.parent

    @property
    def ref(self) -> str:
        """The reference to pass to ``ibek pattern add``."""
        return f"{self.library}:{self.module}@{self.version}"


@dataclass
class PatternPlan:
    """Which of an IOC's modules could come from a pattern.

    ``patterns`` holds one entry per module, in the order the modules first appear.
    ``build_time`` maps each other pattern module to the reason it stays build-time;
    modules with no pattern at all are not listed.
    """

    patterns: list[Pattern] = field(default_factory=list)
    build_time: dict[str, str] = field(default_factory=dict)

    @property
    def refs(self) -> list[str]:
        return [p.ref for p in self.patterns]


def _library_version(library: Path) -> str:
    """The release tag the library checkout is at, which must be clean."""
    git = ["git", "-C", str(library)]
    result = subprocess.run(
        [*git, "describe", "--tags", "--exact-match", "HEAD"],
        capture_output=True,
        text=True,
    )
    tag = result.stdout.strip()
    if result.returncode != 0 or not tag:
        raise PatternIndexError(
            f"{library.name} is not checked out at a release tag, so there is no "
            f"version to vendor its patterns at. Check out the committed pin:\n"
            f"    git submodule update --init {library.name}"
        )
    status = subprocess.run(
        [*git, "status", "--porcelain"], capture_output=True, text=True
    )
    if status.returncode != 0 or status.stdout.strip():
        raise PatternIndexError(
            f"{library.name} has local changes, so its patterns are not those of "
            f"{tag}. Restore the committed pin:\n"
            f"    git submodule update --init --force {library.name}"
        )
    return tag


def library_cache() -> Path:
    """Where an installed builder2ibek keeps its clones of the libraries."""
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "builder2ibek" / "patterns"


def _has_patterns(library: Path) -> bool:
    return any(library.glob("*/*.ibek.support.yaml"))


def fetch_library(name: str, version: str, cache_dir: Path, url: str) -> Path:
    """A shallow clone of library ``name`` at tag ``version``, kept in ``cache_dir``.

    Cloned once into ``<cache_dir>/<name>@<version>``; a release tag does not move, so
    the clone is used as it is from then on.
    """
    dest = cache_dir / f"{name}@{version}"
    if _has_patterns(dest):
        return dest
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_dir, prefix=f".{name}@") as tmp:
        clone = Path(tmp) / "clone"
        result = subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--branch",
                version,
                "--",
                url,
                str(clone),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise PatternIndexError(
                f"cannot fetch {name} {version} from {url}: {result.stderr.strip()}"
            )
        shutil.rmtree(dest, ignore_errors=True)
        clone.rename(dest)
    return dest


class PatternIndex:
    """The patterns in the pinned libraries, keyed by module."""

    def __init__(
        self,
        root: Path = _project_root,
        cache_dir: Path | None = None,
        urls: Mapping[str, str] = DEFAULT_LIBRARIES,
    ):
        """Index the libraries checked out under ``root``.

        A library with no checkout there is cloned into ``cache_dir`` at its tag in
        :data:`LIBRARY_VERSIONS`, from ``urls``; with no ``cache_dir``, it is an
        error.
        """
        self.root = root
        self.patterns: dict[str, Pattern] = {}
        self._ioc_models: dict[str, Any] = {}
        yml = YAML(typ="safe", pure=True)

        for name in LIBRARIES:
            library = root / name
            if _has_patterns(library):
                version = _library_version(library)
            elif cache_dir is not None:
                version = LIBRARY_VERSIONS[name]
                library = fetch_library(name, version, cache_dir, urls[name])
            else:
                raise PatternIndexError(
                    f"no patterns found in {library}; in a builder2ibek checkout, "
                    f"initialise the submodule:\n    git submodule update --init {name}"
                )
            for folder in sorted(p for p in library.iterdir() if p.is_dir()):
                support_yaml = folder / f"{folder.name}.ibek.support.yaml"
                if not support_yaml.is_file():
                    continue
                data = yml.load(support_yaml.read_text())
                module = data.get("module")
                if module != folder.name:
                    raise PatternIndexError(
                        f"{support_yaml} declares module {module!r}; a pattern "
                        f"folder is vendored by its folder name, so the two must match"
                    )
                if module in self.patterns:
                    raise PatternIndexError(
                        f"pattern {module!r} is in both {self.patterns[module].library}"
                        f" and {name}"
                    )
                self.patterns[module] = Pattern(
                    library=name,
                    module=module,
                    version=version,
                    models=frozenset(
                        m["name"] for m in data.get("entity_models") or []
                    ),
                    support_yaml=support_yaml,
                )

    def pattern_for_module(self, module: str) -> Pattern | None:
        """The pattern builder2ibek may use for a module, or None.

        None when there is no pattern, or when its pattern differs from the
        module's generic model.
        """
        if module in GENERIC_DIFFERS:
            return None
        return self.patterns.get(module)

    def _ioc_model(self, pattern: Pattern) -> Any:
        model = self._ioc_models.get(pattern.module)
        if model is None:
            entity_models = EntityFactory().make_entity_models([pattern.support_yaml])
            model = IocFactory().make_ioc_model(entity_models)
            self._ioc_models[pattern.module] = model
        return model

    def rejects(self, pattern: Pattern, entities: list[Mapping[str, Any]]) -> str:
        """Why the pattern model rejects these entities, or "" if it accepts them."""
        types = {str(e["type"]).partition(".")[2] for e in entities}
        missing = sorted(types - pattern.models)
        if missing:
            return f"{pattern.ref} has no model " + ", ".join(
                f"{pattern.module}.{m}" for m in missing
            )
        # ibek registers each entity's id in one global table, so start it empty
        # and leave it empty: these entities are only being checked
        clear_entity_model_ids()
        try:
            with warnings.catch_warnings():
                # raised from inside ibek's Entity, not from anything here
                warnings.simplefilter("ignore", PydanticDeprecatedSince211)
                self._ioc_model(pattern)(
                    ioc_name="validate",
                    description="validate",
                    entities=[dict(e) for e in entities],
                )
        except ValidationError as e:
            error = e.errors()[0]
            where = ".".join(str(part) for part in error["loc"][2:])
            return f"{pattern.ref} rejects {where}: {error['msg']}"
        except ValueError as e:
            return f"{pattern.ref} rejects an entity: {e}"
        finally:
            clear_entity_model_ids()
        return ""

    def plan(self, entities: Iterable[Mapping[str, Any]]) -> PatternPlan:
        """Decide which of an IOC's modules could come from a pattern."""
        by_module: dict[str, list[Mapping[str, Any]]] = {}
        for entity in entities:
            module = str(entity["type"]).partition(".")[0]
            if module in self.patterns:
                by_module.setdefault(module, []).append(entity)

        plan = PatternPlan()
        for module, module_entities in by_module.items():
            pattern = self.pattern_for_module(module)
            if pattern is None:
                plan.build_time[module] = (
                    f"{self.patterns[module].ref} differs from the generic model "
                    f"of {module}"
                )
                continue
            reason = self.rejects(pattern, module_entities)
            if reason:
                plan.build_time[module] = reason
                continue
            plan.patterns.append(pattern)
        return plan


@cache
def _index_or_error() -> PatternIndex | PatternIndexError:
    try:
        return PatternIndex(cache_dir=library_cache())
    except PatternIndexError as e:
        return e


def pattern_index() -> PatternIndex:
    """The index of the pinned libraries, read once.

    From the submodules of a checkout, else from the user's cache, cloning a
    library there the first time. A failure is raised again on every call
    without another attempt.
    """
    index = _index_or_error()
    if isinstance(index, PatternIndexError):
        raise index
    return index
