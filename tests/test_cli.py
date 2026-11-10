import subprocess
import sys

from builder2ibek import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "builder2ibek", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__


def test_xml2yaml_defaults_to_the_xml_path_with_a_yaml_suffix(tmp_path):
    xml = tmp_path / "BL01C-EA-IOC-02.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<components arch="linux-x86_64">\n'
        '  <EPICS_BASE.EpicsEnvSet key="EPICS_CA_MAX_ARRAY_BYTES" value="6000000"/>\n'
        "</components>\n"
    )
    cmd = [sys.executable, "-m", "builder2ibek", "xml2yaml", str(xml)]
    subprocess.run(cmd, check=True, capture_output=True)
    assert (tmp_path / "BL01C-EA-IOC-02.yaml").is_file()
