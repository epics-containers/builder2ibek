import os
import re
import subprocess
from pathlib import Path

import pytest
from filelock import FileLock

REPO_ROOT = Path(__file__).parent.parent
COMMUNITY_SUPPORT = REPO_ROOT / "ibek-support"
DLS_SUPPORT = REPO_ROOT / "ibek-support-dls"

HAS_COMMUNITY_SUPPORT = any(COMMUNITY_SUPPORT.glob("*/*.ibek.support.yaml"))
HAS_DLS_SUPPORT = any(DLS_SUPPORT.glob("*/*.ibek.support.yaml"))

# entity models ibek provides itself, so they need no support repo
BUILTIN_MODULES = {"ibek"}

_MODULE_RE = re.compile(r"^module:\s*(\S+)", re.M)
_ENTITY_TYPE_RE = re.compile(r"^\s*-?\s*type:\s*([A-Za-z0-9_-]+)\.", re.M)


def _declared_modules(support: Path) -> set[str]:
    """The module names declared by the support YAMLs in a support repo.

    Note this is the `module:` key, not the folder name — they differ in case
    for some modules.
    """
    modules = set()
    for support_yaml in support.glob("*/*.ibek.support.yaml"):
        match = _MODULE_RE.search(support_yaml.read_text())
        if match:
            modules.add(match.group(1))
    return modules


COMMUNITY_MODULES = _declared_modules(COMMUNITY_SUPPORT) | BUILTIN_MODULES


def sample_needs_dls(sample_yaml: Path) -> bool:
    """True if a sample uses any entity model ibek-support does not declare.

    Such a model can only come from ibek-support-dls, so the sample cannot be
    generated without that submodule. Derived from the sample rather than
    hardcoded, so it stays correct as modules move between the two repos.
    """
    if not sample_yaml.exists():
        return True
    used = set(_ENTITY_TYPE_RE.findall(sample_yaml.read_text()))
    return not used <= COMMUNITY_MODULES


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


@pytest.fixture(scope="session")
def ibek_defs(tmp_path_factory, worker_id):
    """Populate $EPICS_ROOT/ibek-defs from whichever support repos are present.

    Only tests that run `ibek runtime generate2` need this, so it is requested
    explicitly rather than being autouse — an autouse fixture that skips takes
    the whole session with it, which is how this suite came to run zero tests
    in CI while still reporting success.

    With pytest-xdist, every worker wants to run this — but they all write to
    the same $EPICS_ROOT/ibek-defs, so the classic xdist file-lock pattern
    runs it exactly once and lets the rest wait for the sentinel.
    """
    if not HAS_COMMUNITY_SUPPORT:
        pytest.skip("no support submodules available to build ibek-defs from")
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

requires_support = pytest.mark.skipif(
    not HAS_COMMUNITY_SUPPORT,
    reason="ibek-support submodule not available",
)


@pytest.fixture
def samples():
    return Path(__file__).parent / "samples"
