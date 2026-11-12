"""
Index of the runtime patterns builder2ibek can use in place of compiled support.

A runtime pattern is a support module whose files (``*.ibek.support.yaml``, protocol,
template) are vendored into an IOC instance with ``ibek pattern add``, so the IOC
runs on a stock image instead of one with the module compiled in. The patterns come
from the ibek-runtime-streamdevice library, at its latest release tag unless
:data:`LIBRARY_TAG_ENV` names one. :func:`pattern_index` shallow-clones the library
at that tag into a temporary folder and indexes it: every library folder holding
``<folder>/<folder>.ibek.support.yaml`` is a pattern for the module of that name,
and the support YAML lists its entity models.

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

import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Callable, Iterable, Mapping
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

# The pattern library, named as ibek names it in its library registry
LIBRARY = "ibek-runtime-streamdevice"
LIBRARY_URL = DEFAULT_LIBRARIES[LIBRARY]

# Fixes the library release to index and vendor, in place of the latest one
LIBRARY_TAG_ENV = "BUILDER2IBEK_PATTERN_TAG"

_project_root = Path(__file__).parent.parent.parent


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

# A module with a generic model in neither table stays build-time: the pattern of
# a library release newer than the one the tests check is not trusted until the
# tables decide it.

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
    """The pattern library cannot be listed, cloned or read."""


@dataclass(frozen=True)
class Pattern:
    """One pattern folder of the library at one release tag."""

    library: str
    module: str
    version: str
    models: frozenset[str]
    support_yaml: Path

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


class cache_outcome[T]:  # noqa: N801 -- used as a decorator
    """Cache a function's result, or the exception it raised, for the process.

    A failed network lookup is then not retried for every IOC of a reconvert.
    """

    def __init__(self, fn: Callable[[], T]):
        self.fn = fn
        self.__doc__ = fn.__doc__
        self.cache_clear()

    def cache_clear(self) -> None:
        self.outcome: tuple[T, None] | tuple[None, Exception] | None = None

    def __call__(self) -> T:
        if self.outcome is None:
            try:
                self.outcome = (self.fn(), None)
            except Exception as e:  # noqa: BLE001 -- re-raised by every call
                self.outcome = (None, e)
        value, error = self.outcome
        if error is not None:
            raise error
        return value  # type: ignore[return-value]


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run git without ever prompting for credentials, for at most a minute."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def version_key(tag: str) -> list[int]:
    """Sort key of a release tag such as 0.8.1 or 2.8.26ec8."""
    return [int(n) for n in re.findall(r"\d+", tag)]


def latest_tag(url: str) -> str:
    """The highest release tag of a git repository; pre-release tags are skipped."""
    result = git("ls-remote", "--tags", "--refs", url)
    if result.returncode != 0:
        raise PatternIndexError(f"cannot list the tags of {url}: {result.stderr}")
    tags = [
        ref.rpartition("refs/tags/")[2]
        for ref in result.stdout.split()
        if ref.startswith("refs/tags/")
    ]
    # a release is digits, dots and an optional "ec<n>", e.g. 0.8.1 or 2.8.26ec8
    releases = [t for t in tags if re.fullmatch(r"v?[\d.]+(ec\d+)?", t)]
    if not releases:
        raise PatternIndexError(f"{url} has no release tags")
    return max(releases, key=version_key)


class PatternIndex:
    """The patterns in one checkout of the library, keyed by module."""

    def __init__(self, root: Path, version: str):
        self.root = root
        self.patterns: dict[str, Pattern] = {}
        self._ioc_models: dict[str, Any] = {}
        yml = YAML(typ="safe", pure=True)

        if not any(root.glob("*/*.ibek.support.yaml")):
            raise PatternIndexError(f"no patterns found in {root}")
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
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
            self.patterns[module] = Pattern(
                library=LIBRARY,
                module=module,
                version=version,
                models=frozenset(m["name"] for m in data.get("entity_models") or []),
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
            if module not in ALIGNED and module in generic_modules():
                plan.build_time[module] = (
                    f"{pattern.ref}: pattern not yet aligned with the generic "
                    f"model of {module}"
                )
                continue
            reason = self.rejects(pattern, module_entities)
            if reason:
                plan.build_time[module] = reason
                continue
            plan.patterns.append(pattern)
        return plan


@cache
def generic_modules(root: Path = _project_root) -> frozenset[str]:
    """The modules with a generic model in this checkout's ibek-support*.

    builder2ibek runs from a checkout, so these are the submodules. Warns once,
    on stderr, when there are none.
    """
    support_yamls = list(root.glob("ibek-support*/*/*.ibek.support.yaml"))
    if not support_yamls:
        print(
            f"warning: no ibek-support* checkout in {root}, so a runtime pattern "
            f"is used even where its module has a generic model",
            file=sys.stderr,
        )
    found = set()
    for support_yaml in support_yamls:
        match = re.search(r"^module:\s*(\S+)", support_yaml.read_text(), re.M)
        if match:
            found.add(match.group(1).strip("'\""))
    return frozenset(found)


@cache_outcome
def pattern_index() -> PatternIndex:
    """The index of the library release to convert with, cloned once per process.

    The release is $BUILDER2IBEK_PATTERN_TAG, or else the latest one.
    """
    tag = os.environ.get(LIBRARY_TAG_ENV) or latest_tag(LIBRARY_URL)
    # removed at exit: the index reads support YAMLs as it needs them
    clone = tempfile.mkdtemp(prefix=f"{LIBRARY}-")
    atexit.register(shutil.rmtree, clone, ignore_errors=True)
    result = git(
        "clone", "--quiet", "--depth", "1", "--branch", tag, LIBRARY_URL, cwd=clone
    )
    if result.returncode != 0:
        raise PatternIndexError(
            f"cannot clone {LIBRARY_URL} at {tag}: {result.stderr.strip()}"
        )
    return PatternIndex(Path(clone) / LIBRARY, tag)
