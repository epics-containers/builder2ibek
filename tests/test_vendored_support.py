"""Guard the vendored ibek-support-dls copy against drifting from the submodule.

CI runs the dls samples off tests/vendored-support-dls/ because it cannot reach
Diamond's GitLab. That copy is only as good as its freshness, so these tests run
wherever the real submodule is available and fail if the two have parted company.
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import DLS_SUPPORT
from tests.vendor_support_dls import (
    PIN_FILE,
    SUPPORT_GLOB,
    VENDORED,
    _module_index,
    _modules_used_by_samples,
)

REPO_ROOT = Path(__file__).parent.parent

# A real submodule checkout has a .git file pointing into .git/modules. The
# copy that --install drops in for CI does not, and comparing that against
# itself would pass while proving nothing.
IS_REAL_CHECKOUT = (DLS_SUPPORT / ".git").exists()

needs_real_submodule = pytest.mark.skipif(
    not IS_REAL_CHECKOUT,
    reason="ibek-support-dls is not a real checkout, nothing to compare against",
)


def test_vendored_copy_is_populated():
    """Cheap guard that the vendored tree survived whatever moved it around."""
    assert any(VENDORED.glob(SUPPORT_GLOB)), (
        f"{VENDORED} has no support YAMLs -- "
        f"run `python3 tests/vendor_support_dls.py --update`"
    )


@needs_real_submodule
def test_vendored_copy_matches_the_pinned_submodule():
    """Every vendored file is byte identical to the one it was copied from."""
    stale = []
    for vendored_file in sorted(VENDORED.glob(SUPPORT_GLOB)):
        original = DLS_SUPPORT / vendored_file.parent.name / vendored_file.name
        if not original.exists():
            stale.append(
                f"{vendored_file.parent.name}/{vendored_file.name} (gone upstream)"
            )
        elif original.read_bytes() != vendored_file.read_bytes():
            stale.append(f"{vendored_file.parent.name}/{vendored_file.name} (differs)")

    assert not stale, (
        "vendored ibek-support-dls copy is stale:\n  "
        + "\n  ".join(stale)
        + "\nrun `python3 tests/vendor_support_dls.py --update`"
    )


@needs_real_submodule
def test_vendored_copy_covers_every_module_the_samples_need():
    """A sample using a new dls module must not silently start skipping in CI."""
    community = _module_index(REPO_ROOT / "ibek-support")
    dls = _module_index(DLS_SUPPORT)
    vendored = _module_index(VENDORED)

    needed = {m for m in _modules_used_by_samples() if m in dls and m not in community}
    missing = sorted(needed - set(vendored))

    assert not missing, (
        f"samples need dls modules that are not vendored: {' '.join(missing)}\n"
        f"run `python3 tests/vendor_support_dls.py --update`"
    )


@needs_real_submodule
def test_vendored_copy_records_the_committed_pin():
    """The copy must come from the SHA this repo pins, not a stray checkout."""
    pinned = subprocess.run(
        ["git", "ls-tree", "HEAD", "ibek-support-dls"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[2]

    recorded = PIN_FILE.read_text().splitlines()[1].split()[1]

    assert recorded == pinned, (
        f"vendored copy came from {recorded[:8]} but this repo pins {pinned[:8]} -- "
        f"run `python3 tests/vendor_support_dls.py --update`"
    )
