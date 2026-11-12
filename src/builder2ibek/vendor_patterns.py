"""
Add the runtime patterns a converted IOC uses to its services-repo instance.

The IOC's patterns are those :meth:`~builder2ibek.patterns.PatternIndex.plan`
picks. When every other entity is one the ioc-streamdevice-runtime image builds,
as its published schema says, the IOC is pattern-only: it runs on the latest
published release of that image, which is written into ``values.yaml`` in place
of the services template's placeholder or an older tag of the same image, and
every pattern is added. Any other IOC keeps the image ``values.yaml`` names, and
each pattern is added unless that image's published schema already has the
pattern's entity types, which means the image installs the pattern itself.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import truststore
from ibek.globals import RUNTIME_LOCK_NAME
from ibek.pattern_cmds.lock import RuntimeLock
from ibek.pattern_cmds.schema import (
    SchemaNotFoundError,
    find_image,
    is_instance,
    parse_image_ref,
    resolve_image_ref,
)
from ibek.pattern_cmds.schema import fetch_base_schema as _fetch_base_schema

from builder2ibek.patterns import (
    cache_outcome,
    latest_tag,
    pattern_index,
    version_key,
)

RUNTIME_IMAGE = "ghcr.io/epics-containers/ioc-streamdevice-runtime"
# Fixes the ioc-streamdevice-runtime tag to use, in place of the latest release
RUNTIME_TAG_ENV = "BUILDER2IBEK_RUNTIME_TAG"
# the image of a services template's values.yaml before anyone sets one
IMAGE_PLACEHOLDER = "REPLACE_WITH_IMAGE_URI"


@dataclass
class PatternReport:
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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


@cache
def image_entity_types(image: str) -> frozenset[str] | None:
    """The entity types in an image's published ioc schema, None if unavailable."""
    try:
        schema = _fetch_base_schema(image)
        items = schema["properties"]["entities"]["items"]
        if "$ref" in items:
            items = schema["$defs"][items["$ref"].split("/")[-1]]
        return frozenset(items["discriminator"]["mapping"])
    except Exception:  # noqa: BLE001 -- the caller warns
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
    config = ioc_yaml.resolve().parent
    if config.name == "config" and is_instance(config.parent):
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


def add_patterns(
    entities: Sequence[Mapping[str, Any]], ioc_yaml: Path
) -> PatternReport:
    """Add the runtime patterns of a converted IOC to its instance folder."""
    report = PatternReport()
    plan = pattern_index().plan(entities)
    if not plan.patterns:
        return report
    runtime, warning = runtime_image()
    if warning:
        report.warnings.append(warning)

    instance = instance_folder(ioc_yaml)
    current, image_known = None, True
    if instance is not None:
        try:
            current = find_image(instance)
        except Exception as e:  # noqa: BLE001 -- any unreadable values.yaml
            report.warnings.append(f"cannot read the image of {instance}: {e}")
            image_known = False

    modules = {p.module for p in plan.patterns}
    built = image_entity_types(runtime)
    if built is None:
        report.warnings.append(
            f"runtime image schema unavailable ({runtime}): pattern-only check skipped"
        )
        pattern_only = False
    else:
        pattern_only = all(
            str(e["type"]).partition(".")[0] in modules or e["type"] in built
            for e in entities
        )

    image = current
    todo = list(plan.patterns)
    if (
        pattern_only
        and image_known
        and (current is None or _same_image(current, runtime))
    ):
        image = runtime
    elif current is not None:
        baked = image_entity_types(current)
        if baked is None:
            report.warnings.append(
                f"cannot fetch the ioc schema of {current}; adding every pattern"
            )
        else:
            todo = []
            for pattern in plan.patterns:
                if {f"{pattern.module}.{m}" for m in pattern.models} & baked:
                    report.notes.append(f"{pattern.module}: {current} installs it")
                else:
                    todo.append(pattern)
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
        return report

    if image == runtime and current != runtime:
        done, message = _set_image(instance, runtime)
        (report.notes if done or current else report.warnings).append(message)

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
        # the ioc.yaml was rewritten with the default header, and the image may
        # have changed
        result = _ibek("pattern", "schema", str(instance))
        if result.returncode != 0:
            report.warnings.append(f"ibek pattern schema failed: {result.stderr}")
    return report
