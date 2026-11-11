"""
Vendor the runtime patterns a converted IOC uses into its instance folder.

When :meth:`~builder2ibek.patterns.PatternIndex.plan` sends some of an IOC's
modules to runtime patterns, and every other entity is one the runtime image
builds, the IOC is pattern-only: it runs on ``ioc-streamdevice-runtime`` with
its patterns vendored into the instance. :func:`vendor_patterns` then runs
``ibek pattern add <library>:<module>@<pinned tag>`` for each pattern, into the
instance folder that holds ``config/ioc.yaml``, from the local copy of the
library the index was read from. ibek writes the pattern files,
``runtime-lock.yaml``, ``ioc.schema.json`` and the ``ioc.yaml`` schema header.
builder2ibek records the library's GitHub URL as the lock's source, as a clone
from GitHub would.

A pattern the instance's ``runtime-lock.yaml`` already holds is left as the
lock has it, at the version and with the file selection the services repo
chose: ``ibek pattern check`` verifies its files, and a version other than
builder2ibek's pin is reported.

The image is the one the instance's ``values.yaml`` pins, if it is a tag of
``ioc-streamdevice-runtime``, else :data:`DEFAULT_RUNTIME_IMAGE`, which is
written into a ``values.yaml`` that still holds the services template's
placeholder. An instance that pins any other image, and an IOC that needs
modules the image does not build, are not vendored, and the reason is reported.

``IBEK_SCHEMA_CACHE`` holds the base schemas ibek uses when the network cannot
be reached. The base schema of :data:`DEFAULT_RUNTIME_IMAGE` is part of
builder2ibek, so deciding whether an IOC is pattern-only for it needs no network.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ibek.globals import RUNTIME_LOCK_NAME
from ibek.pattern_cmds.lock import RuntimeLock
from ibek.pattern_cmds.schema import (
    SCHEMA_HEADER,
    SCHEMA_URL_ENV,
    SchemaNotFoundError,
    fetch_base_schema,
    find_image,
    merge_entities,
    parse_image_ref,
    published_schema_url,
    schema_shape_problem,
)
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES, PatternError, source_label
from ruamel.yaml import YAML

from builder2ibek.patterns import (
    Pattern,
    PatternIndex,
    PatternIndexError,
    PatternPlan,
    pattern_index,
)

# The image a pattern-only IOC runs on. It ships asyn, devIocStats, autosave and
# pvlogging, and ibek >= 4.6.1, which vendored patterns need. Its base schema is
# in schemas/: moving to another tag needs that tag's schema there too.
DEFAULT_RUNTIME_IMAGE = "ghcr.io/epics-containers/ioc-streamdevice-runtime:2.8.26ec8"

# The image of a services template's values.yaml, before anyone has set one
IMAGE_PLACEHOLDER = "REPLACE_WITH_IMAGE_URI"
# the placeholder as an image: value, maybe quoted, maybe with a trailing comment
_PLACEHOLDER = re.compile(
    rf"""^([ \t]*image:[ \t]*(["']?)){IMAGE_PLACEHOLDER}(?=\2[ \t]*(\#.*)?\r?$)""",
    re.M,
)

_SCHEMAS = Path(__file__).parent / "schemas"

# the $schema value of the ioc.yaml header ibek writes for an instance schema
INSTANCE_SCHEMA = SCHEMA_HEADER.partition("$schema=")[2]


class VendorError(Exception):
    """``ibek pattern add`` failed."""


@dataclass
class PatternResult:
    """The runtime patterns of one converted IOC.

    ``refs`` are the ``ibek pattern add`` references of a pattern-only IOC:
    vendored when ``vendored`` is True, otherwise only listed. ``image`` is the
    image the IOC runs on, set whenever ``refs`` is. ``decided`` is False when
    the IOC's patterns were not worked out, or were not acted on, so that an
    instance's existing ``runtime-lock.yaml`` says nothing about them.
    """

    refs: list[str] = field(default_factory=list)
    # the patterns the IOC's modules could come from, pattern-only or not
    available: list[str] = field(default_factory=list)
    image: str | None = None
    instance: Path | None = None
    vendored: bool = False
    decided: bool = True
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def instance_folder(ioc_yaml: Path) -> Path | None:
    """The IOC instance folder for ``<instance>/config/ioc.yaml``, else None."""
    config = ioc_yaml.resolve().parent
    if config.name != "config":
        return None
    return config.parent


def kept_schema(ioc_yaml: Path) -> str | None:
    """The ``$schema`` an ``ioc.yaml`` about to be rewritten must keep, or None.

    An instance with a ``runtime-lock.yaml`` whose ``ioc.yaml`` has the header
    ibek wrote keeps it: the instance schema still describes the vendored
    patterns, whatever this conversion goes on to decide.
    """
    instance = instance_folder(ioc_yaml)
    if instance is None or not (instance / RUNTIME_LOCK_NAME).is_file():
        return None
    if not ioc_yaml.is_file():
        return None
    if ioc_yaml.read_text().partition("\n")[0] != SCHEMA_HEADER:
        return None
    return INSTANCE_SCHEMA


def _schema_file(image: str) -> Path:
    ref = parse_image_ref(image)
    return _SCHEMAS / f"{ref.path[-1].removesuffix('-runtime')}-{ref.tag}.json"


def write_schema_cache(root: Path) -> None:
    """Lay out the base schema of the default image as ibek caches it in ``root``.

    For use as ``IBEK_SCHEMA_CACHE`` where ibek must not fetch: the tests and
    tests/samples/make_samples.sh.
    """
    ref = parse_image_ref(DEFAULT_RUNTIME_IMAGE)
    *parents, name = ref.path
    folder = root.joinpath(
        ref.host or "docker.io", *parents, name.removesuffix("-runtime")
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ref.tag}.json").write_text(
        _schema_file(DEFAULT_RUNTIME_IMAGE).read_text()
    )
    url = published_schema_url(DEFAULT_RUNTIME_IMAGE)
    (folder / f"{ref.tag}.validators.json").write_text(json.dumps({"url": url}))


@cache
def _packaged_schema(path: Path) -> dict:
    return json.loads(path.read_text())


def _recorded_schema_url(instance: Path | None) -> str | None:
    """The base schema URL the instance's runtime-lock.yaml records, if any."""
    if instance is None or not (instance / RUNTIME_LOCK_NAME).is_file():
        return None
    return _lock(instance).schema_url


def _base_schema(image: str, recorded_url: str | None = None) -> dict:
    """The published base schema of ``image``, found as ibek finds it.

    builder2ibek's copy serves the default image, unless ``IBEK_SCHEMA_URL`` or
    the lock's ``schema_url`` (``recorded_url``) names another source.

    Raises SchemaNotFoundError when it cannot be had: not found, a schema URL
    ibek refuses, or a document without the shape of an ibek IOC schema.
    """
    packaged = _schema_file(image)
    override = os.getenv(SCHEMA_URL_ENV, "").strip()
    if not (recorded_url or override) and (
        image == DEFAULT_RUNTIME_IMAGE or packaged.is_file()
    ):
        return _packaged_schema(packaged)
    return _fetched_schema(
        image, recorded_url, override, os.getenv("IBEK_SCHEMA_CACHE", "")
    )


@cache
def _fetched_schema(
    image: str, recorded_url: str | None, _override: str, _cache_dir: str
) -> dict:
    """ibek's fetch of a base schema, once for each source it can come from."""
    try:
        # ibek reports a fallback to its cache on stdout, xml2yaml's output
        with contextlib.redirect_stdout(io.StringIO()):
            schema = fetch_base_schema(image, recorded_url)
    except PatternError as e:  # a schema URL ibek refuses
        raise SchemaNotFoundError(str(e)) from e
    problem = schema_shape_problem(schema)
    if problem:
        raise SchemaNotFoundError(f"the base schema of {image} {problem}")
    return schema


def _entity_types(schema: Mapping[str, Any]) -> set[str]:
    """The entity types an ibek IOC schema accepts."""
    items = schema["properties"]["entities"]["items"]
    if "$ref" in items:
        items = schema["$defs"][items["$ref"].split("/")[-1]]
    return set(items["discriminator"]["mapping"])


def _same_repository(image: str, other: str) -> bool:
    """True if two image refs name the same image, at any tag."""
    a, b = parse_image_ref(image), parse_image_ref(other)
    return (a.host, a.path) == (b.host, b.path)


def _not_built(
    entities: Iterable[Mapping[str, Any]],
    plan: PatternPlan,
    image: str,
    recorded_url: str | None = None,
) -> list[str]:
    """The modules an IOC needs that are neither patterns nor built into ``image``.

    Raises SchemaNotFoundError when ``image``'s base schema cannot be had.
    """
    built = _entity_types(_base_schema(image, recorded_url))
    patterns = {p.module for p in plan.patterns}
    missing: dict[str, None] = {}
    for entity in entities:
        entity_type = str(entity["type"])
        module = entity_type.partition(".")[0]
        if module not in patterns and entity_type not in built:
            missing[module] = None
    return list(missing)


def _fill_placeholder(instance: Path, image: str) -> bool:
    """Set ``image`` in place of the template's placeholder; True if it was there."""
    values = instance / "values.yaml"
    if not values.is_file():
        return False
    text = values.read_bytes().decode()
    filled, count = _PLACEHOLDER.subn(rf"\g<1>{image}", text)
    if count:
        values.write_bytes(filled.encode())
    return bool(count)


def _ibek(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ibek", *args], capture_output=True, text=True
    )


def _output(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stdout + proc.stderr).strip()


def _lock(instance: Path) -> RuntimeLock:
    try:
        return RuntimeLock(instance / RUNTIME_LOCK_NAME)
    except PatternError as e:
        raise VendorError(str(e)) from e


def _add(pattern: Pattern, instance: Path) -> None:
    """``ibek pattern add`` from the local library, recording its GitHub source."""
    proc = _ibek(
        "pattern", "add", pattern.ref, str(instance),
        "--source", str(pattern.library_path),
    )  # fmt: skip
    # ibek may have written the lock before failing, for example on the schema
    _record_github_source(pattern, instance)
    if proc.returncode != 0:
        raise VendorError(
            f"ibek pattern add {pattern.ref} {instance} failed:\n{_output(proc)}"
        )


def _record_github_source(pattern: Pattern, instance: Path) -> None:
    """Record the library's GitHub URL, not the local copy, as the source of
    the pattern's lock entry, if the lock has one."""
    if not (instance / RUNTIME_LOCK_NAME).is_file():
        return
    lock = _lock(instance)
    entry = lock.patterns.get(pattern.module)
    source = source_label(DEFAULT_LIBRARIES[pattern.library])
    if entry is None or entry.source == source:
        return
    lock.set_pattern(pattern.module, entry.version, source, entry.files, entry.select)
    lock.save()


def _locked_rejects(
    index: PatternIndex,
    pattern: Pattern,
    version: str,
    instance: Path,
    entities: Sequence[Mapping[str, Any]],
) -> str:
    """Why the pattern the instance has vendored rejects the IOC's entities,
    or "" if it accepts them."""
    support_yaml = instance / "config" / pattern.support_yaml.name
    if not support_yaml.is_file():
        return f"{support_yaml} is missing"
    try:
        data = YAML(typ="safe", pure=True).load(support_yaml.read_text())
        models = frozenset(m["name"] for m in data.get("entity_models") or [])
    except Exception as e:  # not a support YAML builder2ibek can read
        return f"cannot read {support_yaml}: {e}"
    vendored = dataclasses.replace(
        pattern, version=version, models=models, support_yaml=support_yaml
    )
    module_entities = [
        e for e in entities if str(e["type"]).partition(".")[0] == pattern.module
    ]
    try:
        return index.rejects(vendored, module_entities)
    except Exception as e:  # a model ibek cannot build
        return f"cannot load {support_yaml}: {e}"


def _signature(schema: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Each entity type an IOC schema accepts, with its parameter names."""
    items = schema["properties"]["entities"]["items"]
    if "$ref" in items:
        items = schema["$defs"][items["$ref"].split("/")[-1]]
    defs = schema.get("$defs", {})
    return {
        entity_type: frozenset(defs.get(ref.split("/")[-1], {}).get("properties", {}))
        for entity_type, ref in items["discriminator"]["mapping"].items()
    }


def _schema_is_current(instance: Path) -> bool:
    """True if the instance's ioc.yaml header and ioc.schema.json still describe
    the entities ``ibek pattern schema`` would give it now: the base schema of
    the image values.yaml pins, merged with the vendored support YAMLs.

    Only entity types and their parameter names are compared, not the whole
    schema, which depends on the ibek and pydantic versions that wrote it: a
    services repo whose own tooling writes the schema keeps its file unless the
    image or the vendored models changed what the IOC may hold. False when that
    cannot be told, for example with an image whose base schema cannot be had.
    """
    ioc_yaml = instance / "config" / "ioc.yaml"
    schema = instance / "ioc.schema.json"
    if not schema.is_file() or not ioc_yaml.is_file():
        return False
    if ioc_yaml.read_text().partition("\n")[0] != SCHEMA_HEADER:
        return False
    image = find_image(instance)
    if image is None:
        return False
    try:
        base = copy.deepcopy(_base_schema(image, _recorded_schema_url(instance)))
        existing = _signature(json.loads(schema.read_text()))
    except (SchemaNotFoundError, ValueError, KeyError, TypeError):
        return False
    support_yamls = sorted((instance / "config").glob("*.ibek.support.yaml"))
    try:
        merged = merge_entities(base, support_yamls)
    except Exception:  # a vendored support YAML ibek cannot load
        return False
    return _signature(merged) == existing


def _vendor(
    index: PatternIndex,
    patterns: list[Pattern],
    instance: Path,
    entities: Sequence[Mapping[str, Any]],
    result: PatternResult,
) -> None:
    locked = _lock(instance).patterns
    added = False
    refs = []
    for pattern in patterns:
        entry = locked.get(pattern.module)
        if entry is None:
            _add(pattern, instance)
            added = True
            refs.append(pattern.ref)
            result.notes.append(f"vendored {pattern.ref} into {instance}")
            continue
        refs.append(f"{pattern.library}:{pattern.module}@{entry.version}")
        lock = instance / RUNTIME_LOCK_NAME
        result.notes.append(f"kept {pattern.module} {entry.version} from {lock}")
        if entry.version != pattern.version:
            result.warnings.append(
                f"{lock} pins {pattern.module} {entry.version}, and builder2ibek's "
                f"pin is {pattern.version}; the lock is left as it is"
            )
        rejected = _locked_rejects(index, pattern, entry.version, instance, entities)
        if rejected:
            result.warnings.append(
                f"the {pattern.module} the instance has vendored does not take this "
                f"IOC's entities, so generate2 will fail: {rejected}. Update the "
                f"pattern in {lock}, or remove its entry and files and convert again"
            )
    # the versions the instance holds, which the lock may pin apart from ours
    result.refs = refs
    if any(p.module in locked for p in patterns):
        check = _ibek("pattern", "check", str(instance))
        if check.returncode != 0:
            result.warnings.append(
                f"ibek pattern check {instance} failed:\n{_output(check)}"
            )
    if not added and not _schema_is_current(instance):
        # ibek sets the header and writes the schema afresh
        schema = _ibek("pattern", "schema", str(instance))
        if schema.returncode != 0:
            result.warnings.append(
                f"ibek pattern schema {instance} failed:\n{_output(schema)}"
            )
    result.vendored = True


def vendor_patterns(
    entities: Sequence[Mapping[str, Any]], ioc_yaml: Path, vendor: bool = True
) -> PatternResult:
    """Vendor the patterns of a pattern-only IOC into the instance of ``ioc_yaml``.

    ``ioc_yaml`` must already be written: ibek rewrites its schema header. With
    ``vendor`` False the patterns and image are worked out and reported, and
    nothing is written.
    """
    result = PatternResult(instance=instance_folder(ioc_yaml))
    _plan_and_vendor(entities, ioc_yaml, vendor, result)
    instance = result.instance
    if instance is None or not (instance / RUNTIME_LOCK_NAME).is_file():
        return result
    lock = instance / RUNTIME_LOCK_NAME
    if not result.decided:
        result.notes.append(f"patterns not considered; {lock} left as is")
        return result
    modules = {ref.partition(":")[2].partition("@")[0] for ref in result.refs}
    stale = sorted(set(_lock(instance).patterns) - modules)
    if stale and result.vendored:
        result.warnings.append(
            f"{lock} also holds {', '.join(stale)}, which this IOC does not use: "
            "remove those entries and their files"
        )
    elif stale and not result.available:
        result.warnings.append(
            f"{lock} holds {', '.join(stale)}, and this IOC uses no runtime "
            "pattern: remove those entries and their files by hand"
        )
    elif stale:
        result.warnings.append(
            f"{lock} holds {', '.join(stale)}, and this IOC is not pattern-only "
            "(see the warning above): remove the patterns it does not use by hand"
        )
    return result


_index_warned = False


def _plan_and_vendor(
    entities: Sequence[Mapping[str, Any]],
    ioc_yaml: Path,
    vendor: bool,
    result: PatternResult,
) -> None:
    global _index_warned
    try:
        index = pattern_index()
    except PatternIndexError as e:
        result.decided = False
        if not _index_warned:
            _index_warned = True
            result.warnings.append(f"runtime patterns not considered: {e}")
        return
    plan = index.plan(entities)
    if not plan.patterns:
        return
    refs = plan.refs
    result.available = refs
    available = f"\n  patterns available: {', '.join(refs)}"

    instance = result.instance
    pinned = find_image(instance) if instance is not None else None
    image = DEFAULT_RUNTIME_IMAGE
    if pinned is not None:
        if not _same_repository(pinned, DEFAULT_RUNTIME_IMAGE):
            result.decided = False
            result.warnings.append(
                f"patterns not vendored: values.yaml pins image {pinned}, and "
                f"xml2yaml vendors patterns only for an IOC on "
                f"{DEFAULT_RUNTIME_IMAGE.rpartition(':')[0]}" + available
            )
            return
        image = pinned

    try:
        missing = _not_built(entities, plan, image, _recorded_schema_url(instance))
    except SchemaNotFoundError as e:
        result.decided = False
        result.warnings.append(
            f"patterns not vendored: cannot tell which modules {image} builds: {e}"
            + available
        )
        return
    if missing:
        reasons = [
            f"\n  {module}: {plan.build_time[module]}"
            for module in missing
            if module in plan.build_time
        ]
        result.warnings.append(
            "patterns not vendored: the IOC also needs "
            f"{', '.join(missing)}, which {image} does not build"
            + "".join(reasons)
            + available
        )
        return

    result.refs = refs
    result.image = image
    if instance is None:
        result.warnings.append(
            f"patterns not vendored: {ioc_yaml} is not in the config/ folder of an "
            f"IOC instance\n  patterns: {', '.join(refs)}\n  image: {image}"
        )
        return
    if not vendor:
        result.decided = False
        result.notes.append(
            f"patterns not vendored (--no-vendor): {', '.join(refs)}\nimage: {image}"
        )
        return

    changes = sorted({index.changes_message(p.library) for p in plan.patterns} - {""})
    if changes:
        result.decided = False
        result.warnings.extend(f"patterns not vendored: {c}" for c in changes)
        return

    values = instance / "values.yaml"
    if pinned is None:
        if _fill_placeholder(instance, image):
            result.notes.append(f"set image {image} in {values}")
        elif values.is_file() and IMAGE_PLACEHOLDER in values.read_text():
            result.warnings.append(
                f"{values} holds {IMAGE_PLACEHOLDER} in a form xml2yaml does not "
                f"replace: set ioc-instance.image to {image} by hand"
            )
    _vendor(index, plan.patterns, instance, entities, result)
    result.notes.append(f"image: {image}")

    if ioc_yaml.read_text().partition("\n")[0] != SCHEMA_HEADER:
        if find_image(instance) is None:
            result.warnings.append(
                f"{instance.name} pins no image ibek can use (one with a registry "
                f"path and a tag), so ibek wrote no ioc.schema.json: set "
                f"ioc-instance.image to {image} in values.yaml, then run "
                f"`ibek pattern schema {instance}`"
            )
        else:
            result.warnings.append(
                f"ibek wrote no ioc.schema.json for {instance.name} (image "
                f"{image}); run `ibek pattern schema {instance}` to see why"
            )
