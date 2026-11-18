"""
Index of the runtime patterns builder2ibek can use in place of compiled support.

A runtime pattern is a support module whose files (``*.ibek.support.yaml``, protocol,
template) are vendored into an IOC instance with ``ibek pattern add``, so the IOC
runs on a stock image instead of one with the module compiled in. The patterns come
from the libraries in :data:`LIBRARIES`, ibek-runtime-streamdevice and
ibek-runtime-support, each at its latest release tag unless the environment
variable :data:`LIBRARIES` names for that library is set. :func:`pattern_index`
shallow-clones each library at its tag into a temporary folder and indexes it:
every library folder holding ``<folder>/<folder>.ibek.support.yaml`` is a pattern
for the module of that name, and the support YAML lists its entity models. Only
the beamline modules of ibek-runtime-support and its AreaDetector patterns
(:data:`~builder2ibek.support_defaults.AREADETECTOR_PATTERNS`) are indexed; an
IOC that uses one of its other modules gets a warning (see
builder2ibek.vendor_patterns). A module may have a
pattern in only one library. A library that cannot be indexed is left out, so
that the other's patterns are still used.

:meth:`PatternIndex.plan` decides, for one converted IOC, which modules could come
from a pattern. A module goes to its pattern when:

- it is not listed in :data:`GENERIC_DIFFERS`. Those modules also have a generic
  model in ``ibek-support*`` that their pattern does not match, so an entity valid
  for one is not the same device for the other;
- no parameter the IOC's entities leave to the generic model's default has a
  different default in the pattern: builder2ibek drops a value equal to the
  generic default, so the pattern would fill in its own;
- every one of the IOC's entities of that module validates against the pattern
  model. A module is vendored whole or not at all, so one entity the pattern
  rejects keeps the whole module build-time.

Any other module stays build-time, so it needs an image with the module compiled
in, and the plan says why. Which modules a given image already builds is not known
here, so a plan says what could come from a pattern, not what must.

A beamline module (:func:`is_beamline_module`) never stays build-time: beamline
modules are not compiled into generic IOCs. :func:`drop_beamline_entities` takes
out of the IOC each of its entities that the module's pattern does not take, before
the ioc.yaml is written, and :meth:`PatternIndex.plan` sends the module to its
pattern without the rules above, which are about generic models.
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ibek.entity_factory import EntityFactory
from ibek.ioc import clear_entity_model_ids, id_to_entity
from ibek.ioc_factory import IocFactory
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES
from pydantic import ValidationError
from pydantic.warnings import PydanticDeprecatedSince211
from ruamel.yaml import YAML

from builder2ibek.support_defaults import (
    builder_module_target,
    entity_defaults,
    generic_param_types,
    is_beamline_module,
    routes_to_support_pattern,
    values_match,
)

# The pattern libraries, named as ibek names them in its library registry, each
# with the environment variable that fixes the release to index and vendor in
# place of the latest one
STREAMDEVICE_LIBRARY = "ibek-runtime-streamdevice"
SUPPORT_LIBRARY = "ibek-runtime-support"
LIBRARIES: dict[str, str] = {
    STREAMDEVICE_LIBRARY: "BUILDER2IBEK_PATTERN_TAG",
    SUPPORT_LIBRARY: "BUILDER2IBEK_SUPPORT_PATTERN_TAG",
}

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
ALIGNED: frozenset[str] = frozenset({"oxCryo", "strainGauge"})

# A module with a generic model in neither table stays build-time: the pattern of
# a library release newer than the one the tests check is not trusted until the
# tables decide it.

# The pattern model differs from the generic one: a model or parameter is missing or
# renamed, a type or default changed. The module stays build-time until its pattern
# is aligned with the generic model, and aligning one means moving it to ALIGNED.
GENERIC_DIFFERS: frozenset[str] = frozenset(
    {
        "digitelMpc",
        "lakeshore340",
        "leybold",
        "mks937a",
        "mks937b",
        "motomanNX100",
    }
)


class PatternIndexError(Exception):
    """The pattern library cannot be listed, cloned or read."""


class BeamlinePatternError(Exception):
    """An IOC has beamline entities, but the pattern libraries cannot be indexed.

    Its conversion fails rather than drop entities that a pattern may well take.
    """


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


def module_of(entity: Mapping[str, Any]) -> str:
    """The module of an entity, from its type."""
    return str(entity["type"]).partition(".")[0]


def params_of_type(
    entity: Mapping[str, Any], types: Mapping[str, str] | None, typ: str
) -> set[str]:
    """The values an entity gives its model's parameters of one type.

    ``types`` maps each parameter of the model to its type; with no model there
    are none. A Jinja value is left out: it names nothing until rendered.
    """
    return {
        entity[param]
        for param, t in (types or {}).items()
        if t == typ and isinstance(entity.get(param), str) and "{{" not in entity[param]
    }


class _ForeignEntity:
    """Stands in for an entity of another module that a checked entity refers to.

    ibek resolves an ``object`` parameter by looking its id up among the entities
    it has validated; :meth:`PatternIndex.rejects` validates only one module's.
    """

    def __init__(self, id: str):
        self.id = id

    def __str__(self) -> str:
        return self.id


class PatternIndex:
    """The patterns of the indexed library checkouts, keyed by module."""

    def __init__(
        self,
        root: Path,
        version: str,
        library: str = STREAMDEVICE_LIBRARY,
        only: Callable[[str], bool] | None = None,
    ):
        """Index the library checked out at ``root``.

        ``only``, when given, picks the pattern folders to index by name.
        """
        # the release indexed of each library
        self.libraries: dict[str, str] = {library: version}
        # why each library that could not be indexed was not
        self.failures: dict[str, str] = {}
        # why each beamline module ibek-runtime-support cannot serve does not
        self.module_failures: dict[str, str] = {}
        self.patterns: dict[str, Pattern] = {}
        # the library and release of each pattern folder ``only`` left out
        self.unindexed: dict[str, str] = {}
        self._ioc_models: dict[str, Any] = {}
        self._specs: dict[str, dict[str, dict[str, Any]]] = {}
        yml = YAML(typ="safe", pure=True)

        if not any(root.glob("*/*.ibek.support.yaml")):
            raise PatternIndexError(f"no patterns found in {root}")
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            support_yaml = folder / f"{folder.name}.ibek.support.yaml"
            if not support_yaml.is_file():
                continue
            if only and not only(folder.name):
                self.unindexed[folder.name] = f"{library}@{version}"
                continue
            data = yml.load(support_yaml.read_text())
            module = data.get("module")
            if module != folder.name:
                raise PatternIndexError(
                    f"{support_yaml} declares module {module!r}; a pattern "
                    f"folder is vendored by its folder name, so the two must match"
                )
            self.patterns[module] = Pattern(
                library=library,
                module=module,
                version=version,
                models=frozenset(m["name"] for m in data.get("entity_models") or []),
                support_yaml=support_yaml,
            )

    def add(self, other: PatternIndex) -> None:
        """Index the patterns of another library as well.

        A module with a pattern in both is an error: which one to vendor would be
        a guess.
        """
        both = sorted(self.patterns.keys() & other.patterns.keys())
        if both:
            raise PatternIndexError(
                "a module has a pattern in more than one library: "
                + ", ".join(
                    f"{self.patterns[m].ref} and {other.patterns[m].ref}" for m in both
                )
            )
        self.libraries.update(other.libraries)
        self.patterns.update(other.patterns)
        self.unindexed.update(other.unindexed)

    def pattern_for_module(self, module: str) -> Pattern | None:
        """The pattern builder2ibek may use for a module, or None.

        None when there is no pattern, or when its pattern differs from the
        module's generic model.
        """
        if module in GENERIC_DIFFERS:
            return None
        return self.patterns.get(module)

    def default_conflicts(
        self, pattern: Pattern, entities: list[Mapping[str, Any]]
    ) -> str:
        """A parameter these entities leave to a generic default the pattern
        does not share, or "" if there is none.

        builder2ibek drops a value equal to the default of the module's generic
        model, so the pattern's own default would take its place.
        """
        for entity in entities:
            entity_type = str(entity["type"])
            parameters = self.param_specs(entity_type) or {}
            for name, default in entity_defaults(entity_type).items():
                if name in entity or name not in parameters:
                    continue
                spec = parameters[name]
                if "default" not in spec or not values_match(spec["default"], default):
                    return (
                        f"{pattern.ref}: {entity_type}.{name} defaults to "
                        f"{spec.get('default')!r}, not {default!r} as in the "
                        f"generic model"
                    )
        return ""

    def _ioc_model(self, pattern: Pattern) -> Any:
        model = self._ioc_models.get(pattern.module)
        if model is None:
            entity_models = EntityFactory().make_entity_models([pattern.support_yaml])
            model = IocFactory().make_ioc_model(entity_models)
            self._ioc_models[pattern.module] = model
        return model

    def param_specs(self, entity_type: str) -> dict[str, dict[str, Any]] | None:
        """The parameters of the pattern model of an entity type, by name.

        None when no pattern has that model.
        """
        module, _, model = entity_type.partition(".")
        pattern = self.patterns.get(module)
        if pattern is None:
            return None
        specs = self._specs.get(module)
        if specs is None:
            data = YAML(typ="safe", pure=True).load(pattern.support_yaml.read_text())
            specs = {
                m["name"]: {
                    param: spec or {}
                    for param, spec in (m.get("parameters") or {}).items()
                }
                for m in data.get("entity_models") or []
            }
            self._specs[module] = specs
        return specs.get(model)

    def param_types(self, entity_type: str) -> dict[str, str] | None:
        """The type of each parameter of an entity type's pattern model, or None."""
        specs = self.param_specs(entity_type)
        if specs is None:
            return None
        return {param: str(spec.get("type", "")) for param, spec in specs.items()}

    def strip_defaults(self, entity: dict[str, Any]) -> None:
        """Remove the parameters whose values match the pattern model's defaults."""
        for param, spec in (self.param_specs(str(entity["type"])) or {}).items():
            default = spec.get("default")
            if "default" not in spec or (isinstance(default, str) and "{{" in default):
                continue
            if param in entity and values_match(entity[param], default):
                del entity[param]

    def _params_of_type(self, entity: Mapping[str, Any], typ: str) -> set[str]:
        """The values an entity gives the parameters of one type of its model."""
        return params_of_type(entity, self.param_types(str(entity["type"])), typ)

    def ids(self, entity: Mapping[str, Any]) -> set[str]:
        """The ids an entity defines, by its pattern model."""
        return self._params_of_type(entity, "id")

    def foreign_ids(self, entities: Iterable[Mapping[str, Any]]) -> set[str]:
        """The ids these entities refer to that none of them defines."""
        refs: set[str] = set()
        ids: set[str] = set()
        for entity in entities:
            refs |= self._params_of_type(entity, "object")
            ids |= self.ids(entity)
        return refs - ids

    def rejects(
        self,
        pattern: Pattern,
        entities: list[Mapping[str, Any]],
        foreign_ids: Iterable[str] = (),
    ) -> str:
        """Why the pattern model rejects these entities, or "" if it accepts them.

        ``foreign_ids`` are ids defined by entities of other modules, which the
        entities checked may refer to.
        """
        types = {str(e["type"]).partition(".")[2] for e in entities}
        missing = sorted(types - pattern.models)
        if missing:
            return f"{pattern.ref} has no model " + ", ".join(
                f"{pattern.module}.{m}" for m in missing
            )
        # ibek registers each entity's id in one global table, so start it empty
        # and leave it empty: these entities are only being checked
        clear_entity_model_ids()
        for foreign in foreign_ids:
            id_to_entity[foreign] = _ForeignEntity(foreign)  # type: ignore[assignment]
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
        except Exception as e:
            # a beamline module has no build-time route to fall back on, so any
            # failure is a rejection, and drops the entity for review
            if not is_beamline_module(pattern.module):
                raise
            return f"{pattern.ref} rejects an entity: {type(e).__name__}: {e}"
        finally:
            clear_entity_model_ids()
        return ""

    def plan(self, entities: Iterable[Mapping[str, Any]]) -> PatternPlan:
        """Decide which of an IOC's modules could come from a pattern."""
        by_module: dict[str, list[Mapping[str, Any]]] = {}
        for entity in entities:
            module = module_of(entity)
            if module in self.patterns:
                by_module.setdefault(module, []).append(entity)

        plan = PatternPlan()
        for module, module_entities in by_module.items():
            if is_beamline_module(module):
                # no generic model applies: beamline modules are not compiled
                # into generic IOCs
                beamline = self.patterns[module]
                reason = self.rejects(
                    beamline, module_entities, self.foreign_ids(module_entities)
                )
                if reason:
                    plan.build_time[module] = reason
                else:
                    plan.patterns.append(beamline)
                continue
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
            reason = self.default_conflicts(pattern, module_entities) or self.rejects(
                pattern, module_entities
            )
            if reason:
                plan.build_time[module] = reason
                continue
            plan.patterns.append(pattern)
        return plan


@dataclass(frozen=True)
class DroppedEntity:
    """An entity left out of the ioc.yaml for manual review, and why."""

    entity: Mapping[str, Any]
    reason: str


def drop_beamline_entities(
    entities: Sequence[Mapping[str, Any]],
    index: PatternIndex | None,
) -> tuple[list[Mapping[str, Any]], list[DroppedEntity]]:
    """Split an IOC's entities into those to keep and those to drop.

    An entity of a beamline module is kept when the module's pattern has its model
    and takes it. Any other is dropped: the module has no pattern, the pattern has
    no model for it, or the pattern rejects it, when each of the module's entities
    is checked in order along with those accepted before it.

    So is every entity, of any module, that refers to a dropped one: one whose
    known model (the pattern model of a beamline module, else the generic model
    in ibek-support*) has an ``object`` parameter naming the id of a dropped
    entity. That id is the value of an ``id`` parameter of the dropped entity's
    known model or, with no known model, its ``name``. An entity with no known
    model refers to nothing here; generate2 reports any reference it holds.

    Every entity of a beamline builder repo (:func:`builder_module_target`),
    such as BL15I-BUILDER, is dropped too: a builder repo is never a pattern,
    and its templates are to be migrated into the beamline module.

    ``index`` may be None only when no entity is of a beamline module.

    Returns the entities kept and those dropped, each in the order given.
    """
    reasons: dict[int, str] = {}
    by_module: dict[str, list[int]] = {}
    for i, entity in enumerate(entities):
        module = module_of(entity)
        target = builder_module_target(module)
        if target is not None:
            reasons[i] = (
                f"{module} is not a runtime pattern: its templates need "
                f"migrating into the {target} module"
            )
        elif is_beamline_module(module):
            by_module.setdefault(module, []).append(i)
    if not by_module and not reasons:
        return list(entities), []
    if by_module and index is None:
        raise ValueError("beamline entities need the pattern index")

    def types_of(entity: Mapping[str, Any]) -> dict[str, str] | None:
        if index is not None and is_beamline_module(module_of(entity)):
            return index.param_types(str(entity["type"]))
        return generic_param_types(str(entity["type"]))

    def ids_of(entity: Mapping[str, Any]) -> set[str]:
        types = types_of(entity)
        if types is not None:
            return params_of_type(entity, types, "id")
        name = entity.get("name")
        return {name} if isinstance(name, str) else set()

    for module, positions in by_module.items():
        assert index is not None
        pattern = index.patterns.get(module)
        if pattern is None:
            version = index.libraries.get(SUPPORT_LIBRARY, "?")
            reasons.update(
                (i, f"no runtime pattern for {module} in {SUPPORT_LIBRARY}@{version}")
                for i in positions
            )
            continue
        modelled = []
        for i in positions:
            model = str(entities[i]["type"]).partition(".")[2]
            if model in pattern.models:
                modelled.append(entities[i])
            else:
                reasons[i] = f"no model {module}.{model} in {pattern.ref}"
        foreign = index.foreign_ids(modelled)
        for i in reasons.keys() & set(positions):
            foreign -= ids_of(entities[i])
        if not index.rejects(pattern, modelled, foreign):
            continue
        accepted: list[Mapping[str, Any]] = []
        for i in positions:
            if i in reasons:
                continue
            reason = index.rejects(pattern, [*accepted, entities[i]], foreign)
            if reason:
                reasons[i] = reason
            else:
                accepted.append(entities[i])

    # entities that refer to a dropped one go too, and so on
    defined_by = {
        id: str(entities[i]["type"]) for i in reasons for id in ids_of(entities[i])
    }
    found = True
    while found:
        found = False
        for i, entity in enumerate(entities):
            if i in reasons:
                continue
            refs = params_of_type(entity, types_of(entity), "object")
            hits = sorted(r for r in refs if r in defined_by)
            if hits:
                reasons[i] = f"refers to {hits[0]}, a dropped {defined_by[hits[0]]}"
                defined_by.update(dict.fromkeys(ids_of(entity), str(entity["type"])))
                found = True

    kept = [e for i, e in enumerate(entities) if i not in reasons]
    dropped = [DroppedEntity(entities[i], reasons[i]) for i in sorted(reasons)]
    return kept, dropped


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


def _clone(library: str, tag: str) -> Path:
    """Shallow-clone one library at a tag; returns its checkout, removed at
    exit (an index reads support YAMLs as it needs them)."""
    url = DEFAULT_LIBRARIES[library]
    clone = tempfile.mkdtemp(prefix=f"{library}-")
    atexit.register(shutil.rmtree, clone, ignore_errors=True)
    result = git("clone", "--quiet", "--depth", "1", "--branch", tag, url, cwd=clone)
    if result.returncode != 0:
        raise PatternIndexError(f"cannot clone {url} at {tag}: {result.stderr.strip()}")
    return Path(clone) / library


def _index_library(library: str, tag_env: str) -> PatternIndex:
    """Clone one library at its release and index it."""
    tag = os.environ.get(tag_env) or latest_tag(DEFAULT_LIBRARIES[library])
    # ibek-runtime-support also holds patterns of other modules, which
    # builder2ibek does not route to it
    only = routes_to_support_pattern if library == SUPPORT_LIBRARY else None
    return PatternIndex(_clone(library, tag), tag, library, only)


@cache
def library_release(library: str, tag: str) -> PatternIndex:
    """Every pattern of one release of a library, cloned once per process:
    what an image whose ``ibek pattern install`` pins that release installs.
    Raises PatternIndexError when it cannot be cloned or read, and KeyError
    for a library ibek does not know."""
    return PatternIndex(_clone(library, tag), tag, library)


@cache_outcome
def pattern_index() -> PatternIndex:
    """The index of the library releases to convert with, cloned once per process.

    Each library's release is the one its variable in :data:`LIBRARIES` names, or
    else its latest one. A library that cannot be indexed is left out, and
    :attr:`PatternIndex.failures` says why; when none can be, this raises
    PatternIndexError. A beamline module with a pattern in both libraries is
    left out of ibek-runtime-support, with a warning on stderr, and
    :attr:`PatternIndex.module_failures` says why: an IOC that uses it fails.
    """
    index: PatternIndex | None = None
    failures: dict[str, str] = {}
    for library, tag_env in LIBRARIES.items():
        try:
            library_index = _index_library(library, tag_env)
        except Exception as e:  # noqa: BLE001 -- any failure leaves the library out
            failures[library] = str(e) or type(e).__name__
            continue
        if index is None:
            index = library_index
            continue
        clashes: dict[str, str] = {}
        for module in sorted(index.patterns.keys() & library_index.patterns.keys()):
            clashes[module] = (
                f"{module} has a pattern in both {index.patterns[module].ref} and "
                f"{library_index.patterns.pop(module).ref}"
            )
            print(f"warning: {clashes[module]}", file=sys.stderr)
        index.add(library_index)
        index.module_failures.update(clashes)
    if index is None:
        raise PatternIndexError(
            "; ".join(f"{library}: {error}" for library, error in failures.items())
        )
    index.failures = failures
    return index
