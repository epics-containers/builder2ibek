#!/usr/bin/env python3
"""Warn when a submodule pin has fallen behind its remote main.

This is the other half of test_submodule_pins.py, and the two catch opposite
mistakes. That test fails when a checkout has moved off the pin, so the suite is
testing a tree CI will not use. This warns when a pin has *not* moved but
upstream has -- at which point the repo is internally consistent and entirely
green while testing against support modules that are months old. Nothing else
notices that.

Deliberately never fails. A pin lagging main is normal for days at a time and
is often the correct state; it is a thing to be told about, not blocked on. Run
weekly from periodic.yml, and by hand whenever you like:

    python3 tests/check_pin_freshness.py

The runtime pattern libraries are pinned at release tags rather than main, so
those pins are compared with the newest release tag instead. So is the image
pattern-only IOCs run on, builder2ibek.vendor_patterns.DEFAULT_RUNTIME_IMAGE.

ibek-support-dls is on Diamond's internal GitLab, so this can only reach it from
inside the network. From a GitHub runner that submodule is reported unreachable
and skipped rather than treated as a problem.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBMODULES = ("ibek-support", "ibek-support-dls")
# Pinned at release tags; kept in step with builder2ibek.patterns.LIBRARIES, which
# this script does not import so that it runs without the package installed.
TAGGED_SUBMODULES = ("ibek-runtime-streamdevice", "ibek-runtime-support")
LS_REMOTE_TIMEOUT = 30
# Read rather than imported, for the same reason
VENDOR_PATTERNS = REPO_ROOT / "src" / "builder2ibek" / "vendor_patterns.py"
# ioc-streamdevice releases: the StreamDevice version, then ec<n>
IMAGE_TAG = re.compile(r"(\d+)\.(\d+)\.(\d+)ec(\d+)")

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _warn(message: str) -> None:
    """Emit as a GitHub annotation under Actions, plain text elsewhere."""
    if IN_ACTIONS:
        # One line only -- annotations do not render embedded newlines.
        print(f"::warning::{message.replace(chr(10), ' ')}")
    else:
        print(f"WARNING: {message}")


def _committed_pin(submodule: str) -> str:
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", submodule],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out[2]


def _submodule_url(submodule: str) -> str:
    return subprocess.run(
        ["git", "config", "-f", ".gitmodules", f"submodule.{submodule}.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _remote_main(url: str) -> str | None:
    """Tip of main upstream, or None if the remote cannot be reached."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, "refs/heads/main"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def _version_key(tag: str) -> tuple[int, ...]:
    """Sort key for a release tag such as 0.7.3 or v0.2.0.

    Any other tag gives an empty key, and the caller filters those out.
    """
    try:
        return tuple(int(part) for part in tag.removeprefix("v").split("."))
    except ValueError:
        return ()


def _remote_latest_tag(url: str) -> tuple[str, str] | None:
    """(tag, commit) of the newest release tag upstream, or None if unreachable."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    commits: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, ref = line.split()
        tag = ref.removeprefix("refs/tags/")
        # an annotated tag is listed twice; the ^{} line names its commit
        if tag.endswith("^{}"):
            commits[tag.removesuffix("^{}")] = sha
        else:
            commits.setdefault(tag, sha)
    tags = [tag for tag in commits if _version_key(tag)]
    if not tags:
        return None
    latest = max(tags, key=_version_key)
    return latest, commits[latest]


def _remote_tags(url: str) -> list[str] | None:
    """The tags upstream, or None if the remote cannot be reached."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", url],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return [
        line.split()[1].removeprefix("refs/tags/")
        for line in result.stdout.splitlines()
    ]


def _check_runtime_image() -> int:
    """Warn if the default runtime image is not the newest release; 1 if so."""
    match = re.search(r'DEFAULT_RUNTIME_IMAGE = "(.*)"', VENDOR_PATTERNS.read_text())
    assert match, f"no DEFAULT_RUNTIME_IMAGE in {VENDOR_PATTERNS}"
    image = match[1]
    pinned = image.rpartition(":")[2]
    # ghcr.io/epics-containers/ioc-streamdevice-runtime -> its GitHub repo
    repo = image.rpartition(":")[0].removeprefix("ghcr.io/").removesuffix("-runtime")
    tags = _remote_tags(f"https://github.com/{repo}")
    if tags is None:
        print(f"{image}: remote unreachable, skipped")
        return 0
    releases = {
        tuple(int(n) for n in m.groups()): tag
        for tag in tags
        if (m := IMAGE_TAG.fullmatch(tag))
    }
    if not releases:
        print(f"{image}: no releases found upstream, skipped")
        return 0
    latest = releases[max(releases)]
    if latest == pinned:
        print(f"{image}: the newest release")
        return 0
    _warn(
        f"DEFAULT_RUNTIME_IMAGE {image} is not the newest release {latest}. To "
        f"take it: set the tag in {VENDOR_PATTERNS.relative_to(REPO_ROOT)}, add "
        f"its ibek.ioc.schema.json release asset to src/builder2ibek/schemas, and run "
        f"./tests/samples/make_samples.sh"
    )
    return 1


def main() -> int:
    stale = 0
    for submodule in SUBMODULES:
        pinned = _committed_pin(submodule)
        remote = _remote_main(_submodule_url(submodule))

        if remote is None:
            print(f"{submodule}: remote unreachable, skipped")
        elif remote == pinned:
            print(f"{submodule}: up to date with main ({pinned[:8]})")
        else:
            stale += 1
            _warn(
                f"{submodule} pin {pinned[:8]} is behind main {remote[:8]}. "
                f"To take the update: git submodule update --remote {submodule}, "
                f"./tests/samples/make_samples.sh, and for ibek-support-dls also "
                f"python3 tests/vendor_support_dls.py --update"
            )

    for submodule in TAGGED_SUBMODULES:
        pinned = _committed_pin(submodule)
        latest = _remote_latest_tag(_submodule_url(submodule))

        if latest is None:
            print(f"{submodule}: remote unreachable, skipped")
        elif latest[1] == pinned:
            print(f"{submodule}: at the newest release {latest[0]}")
        else:
            stale += 1
            _warn(
                f"{submodule} pin {pinned[:8]} is not the newest release "
                f"{latest[0]}. To take it: git -C {submodule} checkout {latest[0]}, "
                f"set LIBRARY_VERSIONS in src/builder2ibek/patterns.py, commit the "
                f"pin, "
                f"and run tests/test_patterns.py and make_samples.sh"
            )

    stale += _check_runtime_image()

    total = len(SUBMODULES) + len(TAGGED_SUBMODULES) + 1
    print(f"\n{stale} of {total} pins behind main or the newest release")
    # Always 0: this reports, it does not gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
