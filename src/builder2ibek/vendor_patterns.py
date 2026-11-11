"""
Vendor the runtime patterns a converted IOC uses into its instance folder.

When :meth:`~builder2ibek.patterns.PatternIndex.plan` sends some of an IOC's
modules to runtime patterns, and every other entity is one the runtime image
builds, the IOC is pattern-only: it runs on :data:`DEFAULT_RUNTIME_IMAGE` with
its patterns vendored into the instance. :func:`vendor_patterns` then runs
``ibek pattern add <library>:<module>@<pinned tag>`` for each pattern, into the
instance folder that holds ``config/ioc.yaml``. ibek writes the pattern files,
``runtime-lock.yaml``, ``ioc.schema.json`` and the ``ioc.yaml`` schema header;
builder2ibek writes none of those itself. Adding a pattern at the version it is
already locked at rewrites the same files, so a reconversion vendors again.

ibek takes the instance's image from ``values.yaml`` (or ``compose.yml``) and
builds ``ioc.schema.json`` from that image's published base schema. An instance
that pins no image gets its pattern files and lock but no schema; the image to
set is reported.

An IOC that also needs modules the runtime image does not build is not
vendored, and the reason is reported.

ibek's own environment variables apply: ``IBEK_PATTERN_LIBRARIES`` points a
library at another source, such as a local checkout, and ``IBEK_SCHEMA_CACHE``
holds the cached base schemas, which are used when the network cannot be
reached.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ibek.globals import RUNTIME_LOCK_NAME
from ibek.pattern_cmds.schema import (
    SCHEMA_HEADER,
    SchemaNotFoundError,
    fetch_base_schema,
    find_image,
    parse_image_ref,
)
from ruamel.yaml import YAML

from builder2ibek.patterns import PatternIndexError, PatternPlan, pattern_index

# The image a pattern-only IOC runs on. It ships asyn, devIocStats, autosave and
# pvlogging, and ibek >= 4.6.1, which vendored patterns need.
DEFAULT_RUNTIME_IMAGE = "ghcr.io/epics-containers/ioc-streamdevice-runtime:2.8.26ec8"


class VendorError(Exception):
    """``ibek pattern add`` failed."""


@dataclass
class PatternResult:
    """The runtime patterns of one converted IOC.

    ``refs`` are the ``ibek pattern add`` references of a pattern-only IOC:
    vendored when ``vendored`` is True, otherwise only listed. ``image`` is the
    image the IOC needs, set whenever ``refs`` is.
    """

    refs: list[str] = field(default_factory=list)
    image: str | None = None
    instance: Path | None = None
    vendored: bool = False
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def instance_folder(ioc_yaml: Path) -> Path | None:
    """The IOC instance folder for ``<instance>/config/ioc.yaml``, else None."""
    config = ioc_yaml.resolve().parent
    if config.name != "config":
        return None
    return config.parent


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
    entities: Iterable[Mapping[str, Any]], plan: PatternPlan, image: str
) -> list[str]:
    """The modules an IOC needs that are neither patterns nor built into ``image``.

    Raises SchemaNotFoundError when ``image``'s base schema cannot be had.
    """
    built = _entity_types(fetch_base_schema(image))
    patterns = {p.module for p in plan.patterns}
    missing: dict[str, None] = {}
    for entity in entities:
        entity_type = str(entity["type"])
        module = entity_type.partition(".")[0]
        if module not in patterns and entity_type not in built:
            missing[module] = None
    return list(missing)


def _locked_patterns(instance: Path) -> set[str]:
    lock = instance / RUNTIME_LOCK_NAME
    if not lock.is_file():
        return set()
    data = YAML(typ="safe", pure=True).load(lock.read_text()) or {}
    return set(data.get("patterns") or {})


def _ibek_pattern_add(ref: str, instance: Path) -> str:
    """Run ``ibek pattern add`` and return what it printed."""
    proc = subprocess.run(
        [sys.executable, "-m", "ibek", "pattern", "add", ref, str(instance)],
        capture_output=True,
        text=True,
    )
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise VendorError(f"ibek pattern add {ref} {instance} failed:\n{output}")
    return output


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
    if result.instance is not None and vendor:
        stale = _locked_patterns(result.instance) - {
            ref.partition(":")[2].partition("@")[0] for ref in result.refs
        }
        if stale and result.vendored:
            result.warnings.append(
                f"{result.instance / RUNTIME_LOCK_NAME} also holds "
                f"{', '.join(sorted(stale))}, which this IOC no longer uses: "
                "remove those entries and their files"
            )
        elif stale:
            result.warnings.append(
                f"{result.instance / RUNTIME_LOCK_NAME} holds "
                f"{', '.join(sorted(stale))}, but nothing was vendored this time "
                "and ioc.yaml has the default schema header: remove the patterns "
                "the IOC no longer uses, or resolve the warnings above"
            )
    return result


def _plan_and_vendor(
    entities: Sequence[Mapping[str, Any]],
    ioc_yaml: Path,
    vendor: bool,
    result: PatternResult,
) -> None:
    try:
        plan = pattern_index().plan(entities)
    except PatternIndexError as e:
        result.warnings.append(f"runtime patterns not considered: {e}")
        return
    if not plan.patterns:
        return

    refs = plan.refs
    image = DEFAULT_RUNTIME_IMAGE
    try:
        missing = _not_built(entities, plan, image)
    except SchemaNotFoundError as e:
        result.warnings.append(
            f"patterns not vendored: cannot tell which modules {image} builds: {e}"
            f"\n  patterns available: {', '.join(refs)}"
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
            + f"\n  patterns available: {', '.join(refs)}"
        )
        return

    result.refs = refs
    result.image = image
    instance = result.instance
    if instance is None:
        result.warnings.append(
            f"patterns not vendored: {ioc_yaml} is not in the config/ folder of an "
            f"IOC instance\n  patterns: {', '.join(refs)}\n  image: {image}"
        )
        return
    if not vendor:
        result.notes.append(
            f"patterns not vendored (--no-vendor): {', '.join(refs)}\nimage: {image}"
        )
        return

    pinned = find_image(instance)
    if pinned is not None and not _same_repository(pinned, image):
        result.warnings.append(
            f"patterns not vendored: {instance.name} pins image {pinned}, and this "
            f"IOC needs only {image} and its patterns. Set that image in "
            f"values.yaml and convert again.\n  patterns: {', '.join(refs)}"
        )
        return

    for ref in refs:
        _ibek_pattern_add(ref, instance)
        result.notes.append(f"vendored {ref} into {instance}")
    result.vendored = True
    result.notes.append(f"image: {image}")

    if pinned is None:
        result.warnings.append(
            f"{instance.name} pins no image, so ibek wrote no ioc.schema.json: set "
            f"the image to {image} in values.yaml and convert again"
        )
    elif ioc_yaml.read_text().partition("\n")[0] != SCHEMA_HEADER:
        result.warnings.append(
            f"ibek wrote no ioc.schema.json for {instance.name} (image {pinned}); "
            f"run `ibek pattern schema {instance}` to see why"
        )
