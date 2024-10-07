import subprocess
import sys


def test_cli_version():
    cmd = [sys.executable, "-m", "builder2ibek", "file", "--yaml", "out.yaml", "tests/samples/BL45P-MO-IOC-01.xml"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.stderr == b""

    cmd = [sys.executable, "-m", "builder2ibek", "file", "--yaml", "out.yaml", "tests/samples/BL99P-EA-IOC-05.xml"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.stderr == b""

    

