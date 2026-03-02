import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session", autouse=True)
def update_schema():
    """Regenerate the ibek schema before tests so support YAMLs stay in sync."""
    result = subprocess.run(
        [str(REPO_ROOT / "update-schema")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"update-schema failed:\n{result.stderr}"


@pytest.fixture
def samples():
    return Path(__file__).parent / "samples"
