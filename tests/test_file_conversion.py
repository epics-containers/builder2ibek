"""
Tests to validate the full conversion pipeline:
  1. XML → YAML  (builder2ibek xml2yaml)
  2. YAML → st.cmd + ioc.subst  (ibek runtime generate2)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from builder2ibek.convert import convert_file
from builder2ibek.converters.epics_base import InterruptVector
from builder2ibek.vendor_patterns import DEFAULT_RUNTIME_IMAGE
from tests.conftest import (
    DLS_SUPPORT,
    HAS_COMMUNITY_SUPPORT,
    canonical_lock,
    requires_support,
)

SAMPLES = Path(__file__).parent / "samples"

# Every sample runs everywhere. The dls entity models are always resolvable --
# from the submodule locally, or from the vendored copy CI installs -- so there
# is nothing left to mark a sample as conditional on.
SAMPLE_PARAMS = [
    pytest.param(xml, id=xml.stem) for xml in sorted(SAMPLES.glob("*.xml"))
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


def test_dls_models_available():
    """Guard the other half of ibek-defs.

    The samples no longer skip when ibek-support-dls is missing, because the
    vendored copy makes its models available to anyone. If neither is present
    the dls samples just fail, so say why once rather than 15 times.
    """
    assert any(DLS_SUPPORT.glob("*/*.ibek.support.yaml")), (
        "no ibek-support-dls entity models — run "
        "`git submodule update --init ibek-support-dls`, or without GitLab "
        "access `python3 tests/vendor_support_dls.py --install`"
    )


def _instance(root: Path) -> Path:
    """An IOC instance folder pinned to the image pattern-only IOCs run on."""
    instance = root / "instance"
    (instance / "config").mkdir(parents=True)
    (instance / "values.yaml").write_text(
        f"ioc-instance:\n  image: {DEFAULT_RUNTIME_IMAGE}\n"
    )
    return instance


def _expected_patterns(stem: str) -> list[str]:
    """The `ibek pattern add` references a sample vendors, from <stem>.patterns."""
    expected = SAMPLES / f"{stem}.patterns"
    return expected.read_text().splitlines() if expected.exists() else []


def _check_vendored(stem: str, instance: Path, patterns: list[str]):
    """The instance holds exactly the vendored files the sample expects."""
    lock = instance / "runtime-lock.yaml"
    expected_lock = SAMPLES / f"{stem}.runtime-lock.yaml"
    if not patterns:
        assert not lock.exists() and not expected_lock.exists()
        return
    assert canonical_lock(lock.read_text()) == expected_lock.read_text()
    # every file the lock lists is on disk with the hash it records
    check = subprocess.run(
        [sys.executable, "-m", "ibek", "pattern", "check", str(instance)],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    schema = json.loads((instance / "ioc.schema.json").read_text())
    mapping = schema["properties"]["entities"]["items"]["discriminator"]["mapping"]
    for ref in patterns:
        module = ref.partition(":")[2].partition("@")[0]
        assert any(t.startswith(f"{module}.") for t in mapping), ref


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_convert(sample_xml: Path, tmp_path: Path):
    """Test that xml2yaml produces the expected YAML for a sample XML."""
    stem = sample_xml.stem.lower()
    expected_yaml = SAMPLES / f"{stem}.yaml"
    instance = _instance(tmp_path)
    out_yaml = instance / "config" / "ioc.yaml"

    result = convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

    assert out_yaml.read_text() == expected_yaml.read_text()
    patterns = _expected_patterns(stem)
    assert result.patterns == patterns
    assert result.vendored == bool(patterns)
    _check_vendored(stem, instance, patterns)
    # reset the interrupt vector counter
    InterruptVector.reset()


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_generate(sample_xml: Path, ibek_defs, tmp_path: Path):
    """
    Test the full pipeline for a sample XML: XML → YAML → st.cmd + ioc.subst.

    The XML is converted into an instance folder, so a pattern-only sample has
    its patterns vendored there and generate2 reads them from config/.

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

    instance = _instance(tmp_path)
    config = instance / "config"
    ioc_yaml = config / "ioc.yaml"
    patterns_out = tmp_path / "patterns"
    output = tmp_path / "runtime"

    # step 1: XML → YAML (subprocess to avoid converter state leakage)
    result = subprocess.run(
        [
            "builder2ibek",
            "xml2yaml",
            str(sample_xml),
            "--yaml",
            str(ioc_yaml),
            "--patterns-out",
            str(patterns_out),
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
    patterns = _expected_patterns(stem)
    assert patterns_out.read_text().splitlines() == patterns
    _check_vendored(stem, instance, patterns)

    # step 2: YAML → st.cmd + ioc.subst
    result = subprocess.run(
        [
            "ibek",
            "runtime",
            "generate2",
            str(config),
            "--output",
            str(output),
            "--no-pvi",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"generate2 failed for {sample_xml.name}:\n{result.stderr}"
    )

    actual_stcmd = (output / "st.cmd").read_text().rstrip()
    actual_subst = (output / "ioc.subst").read_text().rstrip()

    assert actual_stcmd == expected_stcmd.read_text().rstrip(), (
        f"st.cmd mismatch for {stem}"
    )
    assert actual_subst == expected_subst.read_text().rstrip(), (
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
