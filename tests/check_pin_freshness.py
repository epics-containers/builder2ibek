#!/usr/bin/env python3
"""Warn when a submodule pin has fallen behind its remote main.

This is the other half of test_sample_pins.py, and the two catch opposite
mistakes. That test fails when a pin moves and the samples are not regenerated.
This warns when a pin has *not* moved but upstream has -- at which point the
repo is internally consistent and entirely green while testing against support
modules that are months old. Nothing else notices that.

Deliberately never fails. A pin lagging main is normal for days at a time and
is often the correct state; it is a thing to be told about, not blocked on. Run
weekly from periodic.yml, and by hand whenever you like:

    python3 tests/check_pin_freshness.py

ibek-support-dls is on Diamond's internal GitLab, so this can only reach it from
inside the network. From a GitHub runner that submodule is reported unreachable
and skipped rather than treated as a problem.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBMODULES = ("ibek-support", "ibek-support-dls")
LS_REMOTE_TIMEOUT = 30

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

    print(f"\n{stale} of {len(SUBMODULES)} submodule pins behind main")
    # Always 0: this reports, it does not gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
