import subprocess
import sys
import os

def test_cli_version():
    conversion_samples = ["tests/samples/BL45P-MO-IOC-01.xml",
                           "tests/samples/BL99P-EA-IOC-05.xml"]    
    
    for sample in conversion_samples:
        cmd = [sys.executable, "-m", "builder2ibek", "file", "--yaml", "out.yaml", sample]
        result = subprocess.run(cmd)
        assert result.returncode == 0

    

