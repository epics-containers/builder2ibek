"""update-schema refuses two support folders that declare the same module.

Each case runs a copy of the script over a small fake tree of ibek-support*
folders, with a stub `ibek` on PATH, so it tests the checks and not ibek.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "update-schema"


def _support(root: Path, folder: str, filename: str, body: str) -> Path:
    path = root / folder / filename
    path.parent.mkdir(parents=True)
    path.write_text(body)
    return path


def _run(root: Path, allow: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Run a copy of update-schema in root, with `allow` as its clash allowlist."""
    marker = "module_clash_allowlist=(\n"
    text = SCRIPT.read_text()
    assert marker in text
    entries = "".join(f'    "{entry}"\n' for entry in allow)
    script = root / "update-schema"
    script.write_text(text.replace(marker, marker + entries))
    script.chmod(0o755)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    ibek = bin_dir / "ibek"
    ibek.write_text("#!/bin/sh\necho '{}'\n")
    ibek.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["EPICS_ROOT"] = str(root / "epics")
    return subprocess.run(
        [str(root / "update-schema")],
        capture_output=True,
        text=True,
        env=env,
        cwd=root,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _support(tmp_path, "ibek-support/asyn", "asyn.ibek.support.yaml", "module: asyn\n")
    _support(
        tmp_path, "ibek-support-dls/dlsPLC", "dlsPLC.ibek.support.yaml", "module: x\n"
    )
    return tmp_path


def test_distinct_modules_pass(tree: Path):
    result = _run(tree)
    assert result.returncode == 0, result.stderr
    assert (tree / "epics" / "ibek-defs" / "ioc.schema.json").exists()


def test_same_module_ignoring_case_fails(tree: Path):
    _support(tree, "ibek-support/foo", "foo.ibek.support.yaml", "module: foo\n")
    _support(
        tree, "ibek-support-dls/FOO", "FOO.ibek.support.yaml", "module: 'FOO'\n# x\n"
    )
    result = _run(tree)
    assert result.returncode == 1
    assert "ibek-support/foo" in result.stderr
    assert "ibek-support-dls/FOO" in result.stderr


def test_byte_identical_fork_passes(tree: Path):
    body = "module: fork\nentity_models: []\n"
    _support(tree, "ibek-support/fork", "fork.ibek.support.yaml", body)
    _support(tree, "ibek-support-dls/fork_dls", "fork.ibek.support.yaml", body)
    result = _run(tree)
    assert result.returncode == 0, result.stderr


FAKE_PAIR = "ibek-support-dls/Clash ibek-support/clash"


def test_allowlisted_pair_passes(tree: Path):
    _support(tree, "ibek-support/clash", "clash.ibek.support.yaml", "module: clash\n")
    _support(
        tree, "ibek-support-dls/Clash", "Clash.ibek.support.yaml", "module: Clash\n"
    )
    result = _run(tree, allow=(FAKE_PAIR,))
    assert result.returncode == 0, result.stderr
    assert "known pending duplicate" in result.stderr


def test_allowlist_names_folders_not_modules(tree: Path):
    _support(tree, "ibek-support/clash", "clash.ibek.support.yaml", "module: clash\n")
    _support(
        tree, "ibek-support-dls/clash2", "clash2.ibek.support.yaml", "module: CLASH\n"
    )
    result = _run(tree, allow=(FAKE_PAIR,))
    assert result.returncode == 1
    assert "ibek-support-dls/clash2" in result.stderr


def test_missing_module_fails(tree: Path):
    _support(tree, "ibek-support/bare", "bare.ibek.support.yaml", "entity_models: []\n")
    result = _run(tree)
    assert result.returncode == 1
    assert "declares no top-level module" in result.stderr
