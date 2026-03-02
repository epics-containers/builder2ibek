"""
Tests to validate the full conversion pipeline:
  1. XML → YAML  (builder2ibek xml2yaml)
  2. YAML → st.cmd + ioc.subst  (ibek runtime generate2)
"""

import subprocess
import tempfile
from pathlib import Path

from builder2ibek.convert import convert_file
from builder2ibek.converters.epics_base import InterruptVector


def test_convert(samples: Path):
    """Test that xml2yaml produces the expected YAML for every sample XML."""
    all_samples = samples.glob("*.xml")
    for sample_xml in all_samples:
        sample_yaml = Path(str(sample_xml.with_suffix(".yaml")).lower())
        out_yaml = Path("/tmp") / sample_yaml.name

        convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

        assert out_yaml.read_text() == sample_yaml.read_text()
        # reset the interrupt vector counter
        InterruptVector.reset()


def test_generate(samples: Path):
    """
    Test the full pipeline for every sample XML that has committed generate2
    outputs: XML → YAML → st.cmd + ioc.subst.

    Both steps use subprocesses to avoid global state leakage between
    converter modules across test iterations.
    """
    for sample_xml in sorted(samples.glob("*.xml")):
        stem = sample_xml.stem.lower()
        expected_yaml = samples / f"{stem}.yaml"
        expected_stcmd = samples / f"{stem}.st.cmd"
        expected_subst = samples / f"{stem}.ioc.subst"

        # only test samples that have committed generate2 outputs
        if not expected_stcmd.exists():
            continue

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir)
            ioc_yaml = config / "ioc.yaml"

            # step 1: XML → YAML (subprocess to avoid converter state leakage)
            result = subprocess.run(
                [
                    "builder2ibek",
                    "xml2yaml",
                    str(sample_xml),
                    "--yaml",
                    str(ioc_yaml),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"xml2yaml failed for {sample_xml.name}:\n{result.stderr}"
            )
            assert ioc_yaml.read_text() == expected_yaml.read_text(), (
                f"YAML mismatch for {stem}"
            )

            # step 2: YAML → st.cmd + ioc.subst
            result = subprocess.run(
                [
                    "ibek",
                    "runtime",
                    "generate2",
                    str(config),
                    "--output",
                    str(config),
                    "--no-pvi",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"generate2 failed for {sample_xml.name}:\n{result.stderr}"
            )

            actual_stcmd = (config / "st.cmd").read_text()
            actual_subst = (config / "ioc.subst").read_text()

            assert actual_stcmd == expected_stcmd.read_text(), (
                f"st.cmd mismatch for {stem}"
            )
            assert actual_subst == expected_subst.read_text(), (
                f"ioc.subst mismatch for {stem}"
            )


def test_debug(samples: Path):
    """
    A single test to debug the conversion process (a redundant test, just useful
    for launching the debugger against the convert_file function)
    """
    in_xml = samples / "BL99P-EA-IOC-05.xml"
    out_yml = samples / "BL99P-EA-IOC-05.yaml"
    convert_file(in_xml, out_yml, "/epics/ibek-defs/ioc.schema.json")
