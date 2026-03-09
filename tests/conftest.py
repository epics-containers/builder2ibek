import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DLS_SUPPORT = REPO_ROOT / "ibek-support-dls"
HAS_DLS_SUPPORT = any(DLS_SUPPORT.glob("*/*.ibek.support.yaml"))


@pytest.fixture(scope="session", autouse=True)
def update_schema(tmp_path_factory):
    """Regenerate the ibek schema before tests so support YAMLs stay in sync."""
    if not HAS_DLS_SUPPORT:
        pytest.skip("ibek-support-dls not available")
    env = os.environ.copy()
    # Use a temp dir when /epics is not writable (e.g. CI runners)
    epics_root = Path(env.get("EPICS_ROOT", "/epics"))
    if not os.access(epics_root.parent, os.W_OK) and not epics_root.exists():
        tmpdir = tmp_path_factory.mktemp("epics")
        env["EPICS_ROOT"] = str(tmpdir)
    result = subprocess.run(
        [str(REPO_ROOT / "update-schema")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"update-schema failed:\n{result.stderr}"


requires_dls = pytest.mark.skipif(
    not HAS_DLS_SUPPORT,
    reason="ibek-support-dls submodule not available",
)


@pytest.fixture
def samples():
    return Path(__file__).parent / "samples"
