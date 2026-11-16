"""Pin the runtime pattern versions the tests and samples convert with.

Imported by tests/conftest.py, and run by tests/samples/make_samples.sh, which
exports what it prints.
"""

import os
import shlex
from collections.abc import MutableMapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The runtime pattern library releases and the ioc-streamdevice-runtime tag every
# conversion here uses, so that the samples do not move with upstream releases.
# PATTERN_TAG and SUPPORT_PATTERN_TAG are the submodules' pins.
PATTERN_LIBRARY = REPO_ROOT / "ibek-runtime-streamdevice"
PATTERN_TAG = "0.8.2"
SUPPORT_PATTERN_LIBRARY = REPO_ROOT / "ibek-runtime-support"
SUPPORT_PATTERN_TAG = "0.4.0"
RUNTIME_TAG = "2.8.26ec8"


def pin_patterns(env: MutableMapping[str, str] = os.environ) -> None:
    """Point conversions in ``env`` at the pinned tags, offline.

    git clones of the libraries, by builder2ibek and by `ibek pattern add` in
    its subprocesses, read the submodules instead of GitHub; the lock still
    records the GitHub source.
    """
    env["BUILDER2IBEK_PATTERN_TAG"] = PATTERN_TAG
    env["BUILDER2IBEK_SUPPORT_PATTERN_TAG"] = SUPPORT_PATTERN_TAG
    env["BUILDER2IBEK_RUNTIME_TAG"] = RUNTIME_TAG
    libraries = [PATTERN_LIBRARY, SUPPORT_PATTERN_LIBRARY]
    env["GIT_CONFIG_COUNT"] = str(len(libraries))
    for i, library in enumerate(libraries):
        env[f"GIT_CONFIG_KEY_{i}"] = f"url.file://{library}.insteadOf"
        env[f"GIT_CONFIG_VALUE_{i}"] = (
            f"https://github.com/epics-containers/{library.name}"
        )


if __name__ == "__main__":
    env: dict[str, str] = {}
    pin_patterns(env)
    for key, value in env.items():
        print(f"export {key}={shlex.quote(value)}")
