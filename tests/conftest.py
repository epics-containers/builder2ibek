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


def _epics_root(tmp_path_factory) -> Path:
    """Where ibek-defs should be built.

    Prefer $EPICS_ROOT (or /epics) when it is writable, as in the devcontainer.
    Otherwise use a temp dir — but one derived from getbasetemp().parent, which
    is the same path in every xdist worker, rather than mktemp(), which gives
    each worker a directory of its own.
    """
    epics_root = Path(os.environ.get("EPICS_ROOT", "/epics"))
    if not os.access(epics_root, os.W_OK):
        epics_root = tmp_path_factory.getbasetemp().parent / "epics"
        epics_root.mkdir(exist_ok=True)
    return epics_root


def _run_update_schema():
    result = subprocess.run(
        [str(REPO_ROOT / "update-schema")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
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

    # Export EPICS_ROOT rather than passing it to update-schema alone:
    # test_generate runs `ibek runtime generate2` as a subprocess of its own,
    # and that has to find the same ibek-defs. Setting it only for the
    # update-schema call built the definitions into a directory nothing else
    # could see, so generate2 fell back to /epics -- absent on a CI runner --
    # and resolved only ibek's builtin models.
    os.environ["EPICS_ROOT"] = str(_epics_root(tmp_path_factory))

    if worker_id == "master":
        # non-xdist run: just do it
        _run_update_schema()
        return
    shared_tmp = tmp_path_factory.getbasetemp().parent
    done = shared_tmp / "schema.done"
    with FileLock(str(shared_tmp / "schema.lock")):
        if not done.exists():
            _run_update_schema()
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
