"""Catch a submodule pin moving without the samples being regenerated.

The expected st.cmd/ioc.subst/yaml files are a function of the support module
revisions they were generated from. Bump a pin without re-running
make_samples.sh -- or regenerate against a checkout that is not the pin -- and
the samples describe a state of the world that no longer exists.

That drift is what left 10 sample tests failing before #119, presenting as
inscrutable diffs in generated output rather than as the stale input it was.
GENERATED_AGAINST records the revisions make_samples.sh actually used; this
compares them with the pins the repo commits.

Reads the pins out of git rather than the working tree, so it is meaningful
even where a submodule is not checked out -- CI never clones ibek-support-dls.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
GENERATED_AGAINST = REPO_ROOT / "tests" / "samples" / "GENERATED_AGAINST"
SUBMODULES = ("ibek-support", "ibek-support-dls")


def _committed_pin(submodule: str) -> str:
    """The SHA this repo commits for a submodule, per git's index."""
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", submodule],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out[2]


def _generated_against() -> dict[str, str]:
    if not GENERATED_AGAINST.exists():
        pytest.fail(
            f"{GENERATED_AGAINST.name} is missing -- "
            f"run ./tests/samples/make_samples.sh to record the revisions "
            f"the sample outputs were generated from"
        )
    recorded = {}
    for line in GENERATED_AGAINST.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, sha = line.split()
        recorded[name] = sha
    return recorded


@pytest.mark.parametrize("submodule", SUBMODULES)
def test_samples_were_generated_from_the_committed_pin(submodule: str):
    recorded = _generated_against()

    assert submodule in recorded, (
        f"{GENERATED_AGAINST.name} does not mention {submodule} -- "
        f"re-run ./tests/samples/make_samples.sh"
    )

    pinned = _committed_pin(submodule)
    assert recorded[submodule] == pinned, (
        f"samples were generated against {submodule} {recorded[submodule][:8]} "
        f"but this repo pins {pinned[:8]}.\n"
        f"Either regenerate them:\n"
        f"    git submodule update --checkout {submodule}\n"
        f"    ./tests/samples/make_samples.sh\n"
        f"or restore the pin if the bump was unintended."
    )
