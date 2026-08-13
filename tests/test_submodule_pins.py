"""Guard against testing a submodule tree that is not the one this repo commits.

CI checks each submodule out at the SHA committed here, so the pin is what the
sample tests are really validated against. A local checkout drifts ahead easily
-- a pull inside the submodule, or a sibling superproject that shares it -- and
then the whole suite passes locally while CI regenerates the samples from the
pin and fails on a diff that says nothing about the cause.

Nothing else notices this. test_convert / test_generate regenerate live, so
they compare the samples against whatever is checked out, which is exactly the
tree in question. Compare it against the pin directly instead.
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import COMMUNITY_SUPPORT, DLS_SUPPORT

REPO_ROOT = Path(__file__).parent.parent
SUBMODULES = (COMMUNITY_SUPPORT, DLS_SUPPORT)


def _committed_pin(submodule: Path) -> str:
    """The SHA this repo commits for a submodule."""
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", submodule.name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out[2]


@pytest.mark.parametrize("submodule", SUBMODULES, ids=lambda p: p.name)
def test_checkout_matches_the_committed_pin(submodule: Path):
    # A real checkout has a .git file pointing into .git/modules. CI never
    # clones ibek-support-dls -- it drops in tests/vendored-support-dls -- and
    # a plain directory has no SHA to compare.
    if not (submodule / ".git").exists():
        pytest.skip(f"{submodule.name} is not a checkout, nothing to compare")

    checked_out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=submodule,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert checked_out == _committed_pin(submodule), (
        f"{submodule.name} is checked out at {checked_out[:8]} but this repo "
        f"pins {_committed_pin(submodule)[:8]}, so these results say nothing "
        f"about what CI will do.\n"
        f"Either commit the bump:\n"
        f"    git add {submodule.name} && ./tests/samples/make_samples.sh\n"
        f"or go back to the pin:\n"
        f"    git submodule update --checkout {submodule.name}"
    )
