"""Pin the runtime pattern versions the tests and samples convert with.

Imported by tests/conftest.py, and run by tests/samples/make_samples.sh, which
exports what it prints.
"""

import os
import shlex
from collections.abc import MutableMapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The runtime pattern library release and the ioc-streamdevice-runtime tag every
# conversion here uses, so that the samples do not move with upstream releases.
# PATTERN_TAG is the submodule's pin.
PATTERN_LIBRARY = REPO_ROOT / "ibek-runtime-streamdevice"
PATTERN_TAG = "0.7.3"
RUNTIME_TAG = "2.8.26ec8"


def pin_patterns(env: MutableMapping[str, str] = os.environ) -> None:
    """Point conversions in ``env`` at PATTERN_TAG and RUNTIME_TAG, offline.

    git clones of the library, by builder2ibek and by `ibek pattern add` in its
    subprocesses, read the submodule instead of GitHub; the lock still records
    the GitHub source.
    """
    env["BUILDER2IBEK_PATTERN_TAG"] = PATTERN_TAG
    env["BUILDER2IBEK_RUNTIME_TAG"] = RUNTIME_TAG
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = f"url.file://{PATTERN_LIBRARY}.insteadOf"
    env["GIT_CONFIG_VALUE_0"] = (
        "https://github.com/epics-containers/ibek-runtime-streamdevice"
    )


if __name__ == "__main__":
    env: dict[str, str] = {}
    pin_patterns(env)
    for key, value in env.items():
        print(f"export {key}={shlex.quote(value)}")
