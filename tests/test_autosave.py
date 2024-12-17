import shutil
from pathlib import Path

from builder2ibek.db2autosave import parse_templates


def test_autosave():
    conversion_samples = [
        Path("tests/samples/motor.template"),
    ]

    output = Path("/tmp/autosave")
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir()

    parse_templates(output, conversion_samples)
