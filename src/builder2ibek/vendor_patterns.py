"""
Add the runtime patterns a converted IOC uses to its services-repo instance.

The IOC's patterns are those :meth:`~builder2ibek.patterns.PatternIndex.plan`
picks. When every other entity is one the ioc-streamdevice-runtime image builds,
as its published schema says, the IOC is pattern-only: it runs on the latest
release of that image, which is written into ``values.yaml`` in place of the
services template's placeholder or an older tag of the same image, and every
pattern is added. Any other IOC keeps the image ``values.yaml`` names, and each
pattern is added unless that image's published schema already has the
pattern's entity types, which means the image installs the pattern itself.

Each pattern is added with ``ibek pattern add``, which clones the library and
writes the files, ``runtime-lock.yaml``, ``ioc.schema.json`` and the
``ioc.yaml`` schema header. A pattern ``runtime-lock.yaml`` already holds is
left as it is.

An ``ioc.yaml`` that is not ``<instance>/config/ioc.yaml`` gets nothing: the
patterns and the image are only reported.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ibek.globals import RUNTIME_LOCK_NAME
from ibek.pattern_cmds.lock import RuntimeLock
from ibek.pattern_cmds.schema import fetch_base_schema as _fetch_base_schema
from ibek.pattern_cmds.schema import (
    find_image,
    is_instance,
    parse_image_ref,
    resolve_image_ref,
)
from ibek.pattern_cmds.sources import PatternError

from builder2ibek.patterns import PatternIndexError, latest_tag, pattern_index

RUNTIME_IMAGE = "ghcr.io/epics-containers/ioc-streamdevice-runtime"
# Fixes the ioc-streamdevice-runtime tag to use, in place of the latest release
RUNTIME_TAG_ENV = "BUILDER2IBEK_RUNTIME_TAG"
# the image of a services template's values.yaml before anyone sets one
IMAGE_PLACEHOLDER = "REPLACE_WITH_IMAGE_URI"


@dataclass
class PatternReport:
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@cache
def runtime_image() -> str:
    """The ioc-streamdevice-runtime image to run a pattern-only IOC on."""
    tag = os.environ.get(RUNTIME_TAG_ENV)
    if not tag:
        org, repo, _ = resolve_image_ref(f"{RUNTIME_IMAGE}:latest")
        tag = latest_tag(f"https://github.com/{org}/{repo}")
    return f"{RUNTIME_IMAGE}:{tag}"


@cache
def image_entity_types(image: str) -> frozenset[str] | None:
    """The entity types in an image's published ioc schema, None if unavailable."""
    try:
        schema = _fetch_base_schema(image)
        items = schema["properties"]["entities"]["items"]
        if "$ref" in items:
            items = schema["$defs"][items["$ref"].split("/")[-1]]
        return frozenset(items["discriminator"]["mapping"])
    except (PatternError, KeyError, TypeError):
        return None


def instance_folder(ioc_yaml: Path) -> Path | None:
    """The services-repo instance of ``<instance>/config/ioc.yaml``, else None."""
    config = ioc_yaml.resolve().parent
    if config.name == "config" and is_instance(config.parent):
        return config.parent
    return None


def _set_image(instance: Path, image: str) -> bool:
    """Set the image of a values.yaml holding the placeholder or another tag."""
    values = instance / "values.yaml"
    if not values.is_file():
        return False
    text = values.read_text()
    old = rf"{IMAGE_PLACEHOLDER}|{re.escape(RUNTIME_IMAGE)}:[\w.-]+"
    new = re.sub(old, image, text)
    if new != text:
        values.write_text(new)
    return image in new


def _ibek(*args: str) -> subprocess.CompletedProcess:
    """Run the ibek installed with builder2ibek, else the one on PATH."""
    ibek = shutil.which("ibek", path=Path(sys.executable).parent) or "ibek"
    try:
        return subprocess.run([ibek, *args], capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess([ibek, *args], 1, "", str(e))


def add_patterns(
    entities: Sequence[Mapping[str, Any]], ioc_yaml: Path
) -> PatternReport:
    """Add the runtime patterns of a converted IOC to its instance folder."""
    report = PatternReport()
    try:
        plan = pattern_index().plan(entities)
        if not plan.patterns:
            return report
        runtime = runtime_image()
    except PatternIndexError as e:
        report.warnings.append(f"runtime patterns not checked: {e}")
        return report

    instance = instance_folder(ioc_yaml)
    current = find_image(instance) if instance else None
    modules = {p.module for p in plan.patterns}
    image: str | None = runtime
    built = image_entity_types(runtime)
    if built is None:
        report.warnings.append(f"cannot fetch the ioc schema of {runtime}")
        built = frozenset()
    pattern_only = all(
        str(e["type"]).partition(".")[0] in modules or e["type"] in built
        for e in entities
    )
    if pattern_only and (
        current is None
        or parse_image_ref(current).path == parse_image_ref(runtime).path
    ):
        todo = plan.patterns
    else:
        image = current
        baked = image_entity_types(image) if image else None
        if image and baked is None:
            report.warnings.append(
                f"cannot fetch the ioc schema of {image}; adding every pattern"
            )
        todo = []
        for pattern in plan.patterns:
            if baked and {f"{pattern.module}.{m}" for m in pattern.models} & baked:
                report.notes.append(f"{pattern.module}: {image} installs it")
            else:
                todo.append(pattern)

    if instance is None:
        where = (
            image or "its generic IOC image (patterns that image installs are left out)"
        )
        report.notes += [f"would add runtime pattern {p.ref}" for p in todo]
        report.notes.append(f"image: {where}")
        return report

    if image == runtime and current != runtime:
        if _set_image(instance, runtime):
            report.notes.append(f"image set to {runtime}")
        else:
            report.warnings.append(f"set the image in values.yaml to {runtime}")

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
            report.warnings.append(
                f"ibek pattern add {pattern.ref} failed: {result.stderr.strip()}"
            )
    if not added and lock.patterns:
        # the ioc.yaml was rewritten with the default header; and the image may
        # have changed
        result = _ibek("pattern", "schema", str(instance))
        if result.returncode != 0:
            report.warnings.append(f"ibek pattern schema failed: {result.stderr}")
    return report
