from pathlib import Path

import pytest


@pytest.fixture
def samples():
    return Path(__file__).parent / "samples"
