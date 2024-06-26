import subprocess
import sys

from builder2ibek import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "builder2ibek", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
