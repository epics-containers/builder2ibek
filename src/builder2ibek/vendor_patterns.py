"""
Add the runtime patterns a converted IOC uses to its services-repo instance.

The IOC's patterns are those :meth:`~builder2ibek.patterns.PatternIndex.plan`
picks. When every other entity is one the ioc-streamdevice-runtime image builds,
as its published schema says, the IOC is pattern-only: it runs on the latest
published release of that image, which is written into ``values.yaml`` in place
of the services template's placeholder or an older tag of the same image, and
every pattern is added. Any other IOC keeps the image ``values.yaml`` names, and
each pattern is added unless that image's published schema already has the
pattern's entity types, which means the image installs the pattern itself. A
beamline module's pattern is added whatever the image has: beamline modules are
always deployed per instance.

A schema that cannot be fetched, or a ``values.yaml`` that cannot be read, is a
warning and never stops the conversion. Without the runtime image's schema
there is no pattern-only check, so ``values.yaml`` is left alone; without the
IOC image's schema, or with no image set, every pattern is added.

Each pattern is added with ``ibek pattern add``, which clones the library and
writes the files, ``runtime-lock.yaml``, ``ioc.schema.json`` and the
``ioc.yaml`` schema header. A pattern ``runtime-lock.yaml`` already holds is
left as it is.

An ``ioc.yaml`` that is not ``<instance>/config/ioc.yaml`` gets nothing: the
patterns and the image are only reported.

An image given to :func:`add_patterns` replaces the one ``values.yaml`` names
for all of this: the patterns it installs are left out, a pattern-only IOC
keeps it, and a ``values.yaml`` that still has the placeholder gets it.

Every module the IOC uses is then reported, by :func:`classify_modules`, as a
pattern, build-time (compiled into the image) or unresolved (nothing can run
it). :func:`plan_patterns`, :func:`is_pattern_only` and
:func:`patterns_to_add` make the decisions, so that a caller planning an IOC
without converting it (builder2ibek.beamline2yaml) decides as this does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import truststore
from ibek.globals import RUNTIME_LOCK_NAME
from ibek.pattern_cmds.lock import RuntimeLock
from ibek.pattern_cmds.schema import (
    SchemaFetchError,
    SchemaNotFoundError,
    find_image,
    is_instance,
    parse_image_ref,
    resolve_image_ref,
)
from ibek.pattern_cmds.schema import fetch_base_schema as _fetch_base_schema
from ibek.pattern_cmds.sources import PatternError

from builder2ibek.patterns import (
    Pattern,
    PatternPlan,
    cache_outcome,
    generic_modules,
    is_beamline_module,
    latest_tag,
    module_of,
    pattern_index,
    version_key,
)

RUNTIME_IMAGE = "ghcr.io/epics-containers/ioc-streamdevice-runtime"
# Fixes the ioc-streamdevice-runtime tag to use, in place of the latest release
RUNTIME_TAG_ENV = "BUILDER2IBEK_RUNTIME_TAG"
# the image of a services template's values.yaml before anyone sets one
IMAGE_PLACEHOLDER = "REPLACE_WITH_IMAGE_URI"


@dataclass
class ModuleStatus:
    """How one module of a converted IOC runs."""

    module: str
    #: "pattern", "build-time" or "unresolved"
    kind: str
    reason: str = ""


@dataclass
class PatternReport:
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: each module of the IOC, in the order its entities first appear
    modules: list[ModuleStatus] = field(default_factory=list)
    #: patterns that were to be added and were not, also among the warnings
    errors: list[str] = field(default_factory=list)


@cache_outcome
def runtime_image() -> tuple[str, str]:
    """The ioc-streamdevice-runtime image to run a pattern-only IOC on.

    $BUILDER2IBEK_RUNTIME_TAG, else the latest published GitHub release of the
    generic IOC, else its highest release tag. Returns the image and a warning,
    "" when there is none.
    """
    tag = os.environ.get(RUNTIME_TAG_ENV)
    if tag:
        return f"{RUNTIME_IMAGE}:{tag}", ""
    org, repo, _ = resolve_image_ref(f"{RUNTIME_IMAGE}:latest")
    try:
        tag = _latest_release(f"https://api.github.com/repos/{org}/{repo}")
        return f"{RUNTIME_IMAGE}:{tag}", ""
    except Exception as e:  # noqa: BLE001 -- any failure falls back to the tags
        tag = latest_tag(f"https://github.com/{org}/{repo}")
        return f"{RUNTIME_IMAGE}:{tag}", (
            f"cannot read the latest release of {org}/{repo} ({e}); "
            f"using its highest tag, {tag}, whose image may not be published"
        )


def _latest_release(api: str) -> str:
    """The tag of a GitHub repository's latest published release."""
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    request = urllib.request.Request(
        f"{api}/releases/latest", headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return json.load(response)["tag_name"]


class SchemaUnavailableError(Exception):
    """An image's published ioc schema could not be fetched: a network error,
    not a schema that was never published."""


def fetch_entity_types(image: str) -> frozenset[str] | None:
    """The entity types in an image's published ioc schema.

    None when no schema is published for the image, or what is published is
    not an ibek IOC schema. Raises SchemaUnavailableError when the fetch fails
    and nothing is cached, so that a caller can tell a network problem from a
    missing schema.
    """
    try:
        schema = _fetch_base_schema(image)
    except SchemaFetchError as e:
        raise SchemaUnavailableError(
            f"cannot fetch the ioc schema of {image}: {e}"
        ) from e
    except OSError as e:
        raise SchemaUnavailableError(
            f"cannot fetch the ioc schema of {image}: {e}"
        ) from e
    except (SchemaNotFoundError, PatternError, ValueError):
        # not published, or not JSON
        return None
    try:
        return frozenset(_entity_mapping(schema))
    except (KeyError, TypeError):
        # not an ibek IOC schema
        return None


def _entity_mapping(schema: Mapping[str, Any]) -> Mapping[str, str]:
    """Each entity type of an ibek IOC schema, with the reference to its
    definition. Raises KeyError or TypeError for any other schema."""
    items = schema["properties"]["entities"]["items"]
    if "$ref" in items:
        items = schema["$defs"][items["$ref"].split("/")[-1]]
    return items["discriminator"]["mapping"]


@cache
def image_entity_params(image: str) -> dict[str, frozenset[str]] | None:
    """The parameters each entity type of an image's published ioc schema
    takes, None if the schema is unavailable for any reason. A type whose
    definition allows parameters it does not list is left out."""
    try:
        schema = _fetch_base_schema(image)
        params: dict[str, frozenset[str]] = {}
        for entity_type, ref in _entity_mapping(schema).items():
            definition = schema["$defs"][ref.split("/")[-1]]
            if definition.get("additionalProperties") is False:
                params[entity_type] = frozenset(definition.get("properties", {}))
        return params
    except Exception:  # noqa: BLE001 -- any failure leaves the arguments unchecked
        return None


@cache
def image_entity_types(image: str) -> frozenset[str] | None:
    """The entity types in an image's published ioc schema, None if
    unavailable for any reason; the caller warns."""
    try:
        return fetch_entity_types(image)
    except SchemaUnavailableError:
        return None


def _same_image(image: str, other: str) -> bool:
    """True if two image refs name the same image, at any tag."""
    try:
        a, b = parse_image_ref(image), parse_image_ref(other)
    except SchemaNotFoundError:
        return False
    return (a.host, a.path) == (b.host, b.path)


def instance_folder(ioc_yaml: Path) -> Path | None:
    """The services-repo instance of ``<instance>/config/ioc.yaml``, else None."""
    ioc_yaml = ioc_yaml.resolve()
    config = ioc_yaml.parent
    if (
        ioc_yaml.name == "ioc.yaml"
        and config.name == "config"
        and is_instance(config.parent)
    ):
        return config.parent
    return None


# the image: line of a values.yaml, holding the placeholder or a runtime tag
_IMAGE_LINE = re.compile(
    rf"""^(\s*image:\s*["']?)({IMAGE_PLACEHOLDER}|{re.escape(RUNTIME_IMAGE)}:([\w.-]+))""",
    re.M,
)


def _set_image(instance: Path, image: str) -> tuple[bool, str]:
    """Set the image: line of values.yaml to ``image``.

    Only the placeholder or an older ioc-streamdevice-runtime tag is replaced.
    Returns whether it was set, and why not.
    """
    values = instance / "values.yaml"
    text = values.read_text() if values.is_file() else ""
    match = _IMAGE_LINE.search(text)
    if match is None:
        return False, f"set the image in values.yaml to {image}"
    pinned = match.group(3)
    if pinned and version_key(pinned) >= version_key(image.rpartition(":")[2]):
        return False, f"values.yaml keeps {match.group(2)}, not older {image}"
    values.write_text(text[: match.start(2)] + image + text[match.end(2) :])
    return True, f"image set to {image}"


def _ibek(*args: str) -> subprocess.CompletedProcess:
    """Run the ibek installed with builder2ibek, else the one on PATH."""
    ibek = shutil.which("ibek", path=Path(sys.executable).parent) or "ibek"
    try:
        return subprocess.run([ibek, *args], capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess([ibek, *args], 1, "", str(e))


def plan_patterns(
    entities: Sequence[Mapping[str, Any]], report: PatternReport
) -> PatternPlan:
    """The patterns an IOC's entities come from, with a warning for each
    library that could not be indexed and each module whose pattern
    builder2ibek does not use. Raises PatternIndexError when no library can be
    indexed."""
    index = pattern_index()
    report.warnings += [
        f"{library} patterns not added: {error}"
        for library, error in index.failures.items()
    ]
    # never keep silently the entities of a pattern builder2ibek does not use;
    # a builder repo's (BL15I-BUILDER) were dropped before the ioc.yaml was
    # written (see builder2ibek.patterns.drop_beamline_entities)
    used_modules = sorted({module_of(e) for e in entities})
    report.warnings += [
        f"{module} has a pattern in {index.unindexed[module]} that builder2ibek "
        f"does not use: its entities are kept, so they need an image that "
        f"builds {module}"
        for module in used_modules
        if module in index.unindexed
    ]
    return index.plan(entities)


def sub_entity_args(
    pattern: Pattern, models: Iterable[str]
) -> dict[str, frozenset[str]]:
    """The entity types of other modules that the pattern's ``models`` create
    as sub-entities, each with the arguments they pass it. A sub-entity of the
    pattern's own module is followed into its model."""
    found: dict[str, set[str]] = {}
    todo, seen = list(models), set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for model, entity_type, args in pattern.sub_entities:
            if model != name:
                continue
            module, _, sub_model = entity_type.partition(".")
            if module == pattern.module:
                todo.append(sub_model)
            else:
                found.setdefault(entity_type, set()).update(args)
    return {t: frozenset(args) for t, args in found.items()}


def pattern_gaps(
    entities: Sequence[Mapping[str, Any]],
    patterns: Iterable[Pattern],
    image: str,
    image_types: frozenset[str],
) -> dict[str, str]:
    """Why an image of entity types ``image_types`` cannot run each of these
    patterns, by module; a pattern it can run is not listed.

    It cannot when a sub-entity of a model the IOC uses is of a type the image
    does not build, or passes an argument the image's model of that type does
    not take, as the image's published schema says. With no ``image``, or no
    schema, the arguments are not checked.
    """
    gaps: dict[str, str] = {}
    for pattern in patterns:
        used = {
            str(e["type"]).partition(".")[2]
            for e in entities
            if module_of(e) == pattern.module
        }
        needs = sub_entity_args(pattern, used)
        missing = sorted(needs.keys() - image_types)
        if missing:
            gaps[pattern.module] = (
                f"{image or 'the image'} does not build {', '.join(missing)}, "
                f"which {pattern.ref} needs"
            )
            continue
        takes = (image_entity_params(image) if image and needs else None) or {}
        for entity_type, args in sorted(needs.items()):
            extra = sorted(args - takes[entity_type]) if entity_type in takes else []
            if extra:
                gaps[pattern.module] = (
                    f"{image} {entity_type} takes no {', '.join(extra)}, "
                    f"which {pattern.ref} passes"
                )
                break
    return gaps


def is_pattern_only(
    entities: Sequence[Mapping[str, Any]],
    plan: PatternPlan,
    runtime_types: frozenset[str],
) -> bool:
    """True if every entity is from a planned pattern or one the
    ioc-streamdevice-runtime image, of entity types ``runtime_types``, builds,
    and the image builds every type the patterns' sub-entities need."""
    modules = {p.module for p in plan.patterns}
    return (
        bool(modules)
        and all(module_of(e) in modules or e["type"] in runtime_types for e in entities)
        and not pattern_gaps(entities, plan.patterns, "", runtime_types)
    )


def patterns_to_add(
    entities: Sequence[Mapping[str, Any]],
    plan: PatternPlan,
    image_types: frozenset[str] | None,
) -> list[Pattern]:
    """The planned patterns to add to an IOC on an image of entity types
    ``image_types`` (None when unknown: then every one).

    A pattern whose types the IOC uses the image already has is installed by
    the image, and left out, except a beamline module's: beamline modules are
    deployed per instance, whatever the image builds.
    """
    if image_types is None:
        return list(plan.patterns)
    return [
        pattern
        for pattern in plan.patterns
        if is_beamline_module(pattern.module)
        or not {str(e["type"]) for e in entities if module_of(e) == pattern.module}
        <= image_types
    ]


def classify_modules(
    entities: Sequence[Mapping[str, Any]],
    plan: PatternPlan,
    image: str | None = None,
    image_types: frozenset[str] | None = None,
) -> list[ModuleStatus]:
    """Say for each module of an IOC's entities whether it comes from a runtime
    pattern, is build-time (compiled into the generic IOC image) or is
    unresolved, so that nothing can run it.

    ``image_types`` are the entity types ``image`` builds, None when unknown.
    A module of :func:`patterns_to_add` is a pattern, unless the image cannot
    run it (:func:`pattern_gaps`): then it is unresolved. Any other module whose
    every type the image builds is build-time, a pattern module the image
    installs included, except a beamline module: those are never compiled into
    a generic IOC, so one that is not a pattern is unresolved. With the
    image's types known, the rest are unresolved. Without them, a module is
    build-time when it has a generic model in ``ibek-support*``, and
    unresolved when it has none.
    """
    used: dict[str, set[str]] = {}
    for entity in entities:
        used.setdefault(module_of(entity), set()).add(str(entity["type"]))
    to_add = patterns_to_add(entities, plan, image_types)
    added = {p.module for p in to_add}
    gaps = (
        pattern_gaps(entities, to_add, image or "", image_types)
        if image_types is not None
        else {}
    )
    planned = {p.module for p in plan.patterns}
    statuses: list[ModuleStatus] = []
    for module, types in used.items():
        why = plan.build_time.get(module, "")
        if module in gaps:
            statuses.append(ModuleStatus(module, "unresolved", gaps[module]))
        elif module in added:
            statuses.append(ModuleStatus(module, "pattern"))
        elif is_beamline_module(module):
            reason = "beamline modules come only from runtime patterns" + (
                f": {why}" if why else ""
            )
            statuses.append(ModuleStatus(module, "unresolved", reason))
        elif image_types is not None and types <= image_types:
            reason = f"{image} installs it" if module in planned else why
            statuses.append(ModuleStatus(module, "build-time", reason))
        elif image_types is not None:
            missing = ", ".join(sorted(types - image_types))
            reason = f"{image} does not build {missing}" + (f"; {why}" if why else "")
            statuses.append(ModuleStatus(module, "unresolved", reason))
        elif module in generic_modules() or not generic_modules():
            # with no ibek-support* checkout, generic models are not known
            statuses.append(ModuleStatus(module, "build-time", why))
        else:
            reason = (
                f"no generic model, and {why}"
                if why
                else "no generic model and no runtime pattern"
            )
            statuses.append(ModuleStatus(module, "unresolved", reason))
    return statuses


def module_report(statuses: Iterable[ModuleStatus]) -> tuple[list[str], list[str]]:
    """The notes and warnings that report ``statuses``: one note per kind
    listing its modules, one per build-time module with a reason, and one
    warning per unresolved module."""
    statuses = list(statuses)
    notes: list[str] = []
    for kind in ("pattern", "build-time"):
        names = [s.module for s in statuses if s.kind == kind]
        if names:
            notes.append(f"{kind} modules: " + ", ".join(names))
    notes += [
        f"{s.module} is build-time: {s.reason}"
        for s in statuses
        if s.kind == "build-time" and s.reason
    ]
    warnings = [
        f"unresolved module {s.module}, nothing can run it: {s.reason}"
        for s in statuses
        if s.kind == "unresolved"
    ]
    return notes, warnings


def add_patterns(
    entities: Sequence[Mapping[str, Any]],
    ioc_yaml: Path,
    image: str | None = None,
    image_types: frozenset[str] | None = None,
) -> PatternReport:
    """Add the runtime patterns of a converted IOC to its instance folder, and
    report how each of its modules runs.

    ``image`` is the generic IOC image to plan against in place of the one
    ``values.yaml`` names; an instance whose ``values.yaml`` has the
    placeholder gets it set to ``image``. ``image_types``, when given, are
    its entity types, in place of its published schema's.
    """

    def types_of(ref: str) -> frozenset[str] | None:
        if image_types is not None and ref == image:
            return image_types
        return image_entity_types(ref)

    report = PatternReport()
    plan = plan_patterns(entities, report)
    instance = instance_folder(ioc_yaml)
    current, image_known = image, True
    if instance is not None:
        if image is not None:
            done, message = _set_placeholder(instance, image)
            (report.notes if done else report.warnings).append(message)
        else:
            try:
                current = find_image(instance)
            except Exception as e:  # noqa: BLE001 -- any unreadable values.yaml
                report.warnings.append(f"cannot read the image of {instance}: {e}")
                image_known = False

    planned = current
    if plan.patterns:
        planned = _vendor(
            entities,
            plan,
            instance,
            current,
            image_known,
            image is not None,
            report,
            types_of,
        )
    types = types_of(planned) if planned else None
    report.modules = classify_modules(entities, plan, planned, types)
    notes, warnings = module_report(report.modules)
    report.notes += notes
    report.warnings += warnings
    return report


def _set_placeholder(instance: Path, image: str) -> tuple[bool, str]:
    """Set the image: line of values.yaml to ``image`` if it holds the
    placeholder. Returns whether it was set, and the message for the user."""
    values = instance / "values.yaml"
    text = values.read_text() if values.is_file() else ""
    match = _IMAGE_LINE.search(text)
    if match is not None and match.group(2) == IMAGE_PLACEHOLDER:
        values.write_text(text[: match.start(2)] + image + text[match.end(2) :])
        return True, f"image set to {image}"
    try:
        named = find_image(instance)
    except Exception:  # noqa: BLE001 -- any unreadable values.yaml
        named = None
    if named == image:
        return True, f"image: {image}"
    return False, (
        f"values.yaml names {named or 'no image'}, not {image}: planned against "
        f"{image}; set it in values.yaml"
    )


def _vendor(
    entities: Sequence[Mapping[str, Any]],
    plan: PatternPlan,
    instance: Path | None,
    current: str | None,
    image_known: bool,
    image_given: bool,
    report: PatternReport,
    types_of: Callable[[str], frozenset[str] | None] = image_entity_types,
) -> str | None:
    """Add the planned patterns the IOC's image does not install, or list them
    when there is no instance. Returns the image the IOC runs on, None if
    unknown."""
    built: frozenset[str] | None = None
    runtime = ""
    pattern_only = False
    if not image_given:
        runtime, warning = runtime_image()
        if warning:
            report.warnings.append(warning)
        built = image_entity_types(runtime)
        if built is None:
            report.warnings.append(
                f"runtime image schema unavailable ({runtime}): pattern-only "
                f"check skipped"
            )
        else:
            pattern_only = is_pattern_only(entities, plan, built)

    image = current
    todo = list(plan.patterns)
    if (
        pattern_only
        and image_known
        and (current is None or _same_image(current, runtime))
    ):
        image = runtime
    elif current is not None:
        baked = types_of(current)
        if baked is None:
            report.warnings.append(
                f"cannot fetch the ioc schema of {current}; adding every pattern"
            )
        todo = patterns_to_add(entities, plan, baked)
    elif instance is not None and image_known and built is not None:
        report.warnings.append(
            "mixed IOC with no image set: patterns added to the instance; set the "
            "generic IOC image and re-run xml2yaml to drop patterns the image "
            "already installs"
        )

    if instance is None:
        report.notes += [f"would add runtime pattern {p.ref}" for p in todo]
        where = image or "its generic IOC image (patterns it installs are left out)"
        report.notes.append(f"image: {where}")
        return image

    if image == runtime and current != runtime:
        done, message = _set_image(instance, runtime)
        (report.notes if done or current else report.warnings).append(message)
        if not done and current:
            image = current  # values.yaml still names it

    lock = RuntimeLock(instance / RUNTIME_LOCK_NAME)
    added = False
    for pattern in todo:
        locked = lock.patterns.get(pattern.module)
        if locked is not None:
            if locked.version != pattern.version:
                report.notes.append(
                    f"{pattern.module} stays at {locked.version} as "
                    f"{RUNTIME_LOCK_NAME} has it, not {pattern.version}"
                )
            continue
        result = _ibek("pattern", "add", pattern.ref, str(instance))
        if result.returncode == 0:
            report.notes.append(f"added runtime pattern {pattern.ref}")
            added = True
        else:
            error = f"ibek pattern add {pattern.ref} failed: {result.stderr.strip()}"
            report.warnings.append(error)
            report.errors.append(error)
    if not added and lock.patterns:
        # the ioc.yaml was rewritten with the default header, and the image may
        # have changed
        result = _ibek("pattern", "schema", str(instance))
        if result.returncode != 0:
            error = f"ibek pattern schema failed: {result.stderr}"
            report.warnings.append(error)
            report.errors.append(error)
    return image
