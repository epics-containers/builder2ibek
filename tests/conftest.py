import os
import subprocess
from pathlib import Path

import pytest
from filelock import FileLock

REPO_ROOT = Path(__file__).parent.parent
DLS_SUPPORT = REPO_ROOT / "ibek-support-dls"
HAS_DLS_SUPPORT = any(DLS_SUPPORT.glob("*/*.ibek.support.yaml"))


def _run_update_schema(tmp_path_factory):
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


@pytest.fixture(scope="session", autouse=True)
def update_schema(tmp_path_factory, worker_id):
    """Regenerate the ibek schema before tests so support YAMLs stay in sync.

    With pytest-xdist, every worker wants to run this — but they all write to
    the same $EPICS_ROOT/ibek-defs, so the classic xdist file-lock pattern
    runs it exactly once and lets the rest wait for the sentinel.
    """
    if not HAS_DLS_SUPPORT:
        pytest.skip("ibek-support-dls not available")
    if worker_id == "master":
        # non-xdist run: just do it
        _run_update_schema(tmp_path_factory)
        return
    shared_tmp = tmp_path_factory.getbasetemp().parent
    done = shared_tmp / "schema.done"
    with FileLock(str(shared_tmp / "schema.lock")):
        if not done.exists():
            _run_update_schema(tmp_path_factory)
            done.touch()


requires_dls = pytest.mark.skipif(
    not HAS_DLS_SUPPORT,
    reason="ibek-support-dls submodule not available",
)


@pytest.fixture
def samples():
    return Path(__file__).parent / "samples"
