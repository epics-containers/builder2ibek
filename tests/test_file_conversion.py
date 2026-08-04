"""
Tests to validate the full conversion pipeline:
  1. XML → YAML  (builder2ibek xml2yaml)
  2. YAML → st.cmd + ioc.subst  (ibek runtime generate2)
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from builder2ibek.convert import convert_file
from builder2ibek.converters.epics_base import InterruptVector
from tests.conftest import (
    HAS_COMMUNITY_SUPPORT,
    requires_dls,
    requires_support,
    sample_needs_dls,
)

SAMPLES = Path(__file__).parent / "samples"
SAMPLE_XMLS = sorted(SAMPLES.glob("*.xml"))

# Both conversion steps depend on the support repos: generate2 needs every
# module a sample uses to be in ibek-defs, and xml2yaml consults the same YAMLs
# via support_defaults to strip parameters that match a model's default. So
# mark each sample with what it actually requires, rather than skipping the lot.
SAMPLE_PARAMS = [
    pytest.param(
        xml,
        marks=[requires_dls]
        if sample_needs_dls(SAMPLES / f"{xml.stem.lower()}.yaml")
        else [],
        id=xml.stem,
    )
    for xml in SAMPLE_XMLS
]


def test_support_submodule_present():
    """Guard against the whole suite silently skipping.

    Without ibek-support nearly every test below skips, which previously left
    CI green while running nothing at all. Fail loudly instead.
    """
    assert HAS_COMMUNITY_SUPPORT, (
        "ibek-support submodule not initialised — run "
        "`git submodule update --init ibek-support`"
    )


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_convert(sample_xml: Path):
    """Test that xml2yaml produces the expected YAML for a sample XML."""
    expected_yaml = SAMPLES / f"{sample_xml.stem.lower()}.yaml"
    out_yaml = Path("/tmp") / expected_yaml.name

    convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

    assert out_yaml.read_text() == expected_yaml.read_text()
    # reset the interrupt vector counter
    InterruptVector.reset()


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_generate(sample_xml: Path, ibek_defs):
    """
    Test the full pipeline for a sample XML: XML → YAML → st.cmd + ioc.subst.

    Both steps use subprocesses to avoid global state leakage between
    converter modules across test iterations.
    """
    stem = sample_xml.stem.lower()
    expected_yaml = SAMPLES / f"{stem}.yaml"
    expected_stcmd = SAMPLES / f"{stem}.st.cmd"
    expected_subst = SAMPLES / f"{stem}.ioc.subst"

    assert expected_stcmd.exists(), (
        f"no expected generate2 outputs for {stem} — run make_samples.sh"
    )

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

        actual_stcmd = (config / "st.cmd").read_text().rstrip()
        actual_subst = (config / "ioc.subst").read_text().rstrip()

        assert actual_stcmd == expected_stcmd.read_text().rstrip(), (
            f"st.cmd mismatch for {stem}"
        )
        assert actual_subst == expected_subst.read_text().rstrip(), (
            f"ioc.subst mismatch for {stem}"
        )


@requires_dls
def test_debug(samples: Path):
    """
    A single test to debug the conversion process (a redundant test, just useful
    for launching the debugger against the convert_file function)
    """
    in_xml = samples / "BL99P-EA-IOC-05.xml"
    out_yml = samples / "BL99P-EA-IOC-05.yaml"
    convert_file(in_xml, out_yml, "/epics/ibek-defs/ioc.schema.json")
