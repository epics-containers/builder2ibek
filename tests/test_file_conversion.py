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
from builder2ibek.vendor_patterns import (
    IMAGE_PLACEHOLDER,
    RUNTIME_IMAGE,
    image_entity_types,
)
from tests.conftest import DLS_SUPPORT, HAS_COMMUNITY_SUPPORT, requires_support
from tests.pattern_pins import RUNTIME_TAG

SAMPLES = Path(__file__).parent / "samples"


def _instance_config(root: Path, stem: str) -> Path:
    """The config folder of a services-repo instance made from the template.

    Samples convert into one so that the runtime patterns they use are added,
    as for a real IOC; tests/conftest.py pins their versions.
    """
    instance = root / "services" / stem
    (instance / "config").mkdir(parents=True)
    (instance / "values.yaml").write_text(
        "ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n"
    )
    return instance / "config"


def _skip_without_runtime_schema(stem: str) -> None:
    """A sample with runtime patterns needs the pinned runtime image's schema."""
    image = f"{RUNTIME_IMAGE}:{RUNTIME_TAG}"
    if (SAMPLES / f"{stem}.runtime-lock.yaml").is_file() and (
        image_entity_types(image) is None
    ):
        pytest.skip("needs github.com for the ioc-streamdevice-runtime schema")


# Samples with runtime patterns that also need compiled support, so their
# values.yaml keeps the services template's image placeholder
MIXED_PATTERN_SAMPLES = {"bl04i-mo-ioc-03", "bl05i-mo-ioc-05", "bl18b-ea-ioc-24"}


def _check_patterns(config: Path, stem: str) -> None:
    """The runtime-lock.yaml matches the sample's, or there is none for either."""
    lock = config.parent / "runtime-lock.yaml"
    expected = SAMPLES / f"{stem}.runtime-lock.yaml"
    assert lock.is_file() == expected.is_file()
    if expected.is_file():
        assert lock.read_text() == expected.read_text()
        values = (config.parent / "values.yaml").read_text()
        if stem in MIXED_PATTERN_SAMPLES:
            assert IMAGE_PLACEHOLDER in values
        else:
            # a pattern-only sample runs on the pinned runtime image
            assert f"{RUNTIME_IMAGE}:{RUNTIME_TAG}" in values


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


@requires_support
def test_converting_twice_in_one_process_gives_the_same_yaml(tmp_path: Path):
    """beamline2yaml and reconvert convert many XMLs in one process. This
    sample numbers its interrupt vectors from a converter's counter, so a
    counter carried over from the first conversion changes the second YAML."""
    sample_xml = SAMPLES / "BL19I-VA-IOC-01.xml"
    outputs = []
    for run in ("first", "second"):
        out_yaml = tmp_path / run / "ioc.yaml"
        out_yaml.parent.mkdir()
        convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")
        outputs.append(out_yaml.read_text())

    assert outputs[0] == outputs[1]


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_convert(sample_xml: Path, tmp_path: Path):
    """Test that xml2yaml produces the expected YAML for a sample XML."""
    stem = sample_xml.stem.lower()
    _skip_without_runtime_schema(stem)
    expected_yaml = SAMPLES / f"{stem}.yaml"
    config = _instance_config(tmp_path, stem)
    out_yaml = config / "ioc.yaml"

    result = convert_file(sample_xml, out_yaml, "/epics/ibek-defs/ioc.schema.json")

    assert not [w for w in result.warnings if "patterns not added" in w]

    assert out_yaml.read_text() == expected_yaml.read_text()
    expected_records = SAMPLES / "config" / stem / "records.db"
    out_records = config / "records.db"
    assert out_records.exists() == expected_records.exists()
    if expected_records.exists():
        assert out_records.read_text() == expected_records.read_text()
    _check_patterns(config, stem)


@requires_support
@pytest.mark.parametrize("sample_xml", SAMPLE_PARAMS)
def test_generate(sample_xml: Path, ibek_defs):
    """
    Test the full pipeline for a sample XML: XML → YAML → st.cmd + ioc.subst.

    Both steps use subprocesses to avoid global state leakage between
    converter modules across test iterations.
    """
    stem = sample_xml.stem.lower()
    _skip_without_runtime_schema(stem)
    expected_yaml = SAMPLES / f"{stem}.yaml"
    expected_stcmd = SAMPLES / f"{stem}.st.cmd"
    expected_subst = SAMPLES / f"{stem}.ioc.subst"

    assert expected_stcmd.exists(), (
        f"no expected generate2 outputs for {stem} — run make_samples.sh"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        config = _instance_config(Path(tmpdir), stem)
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
        assert "patterns not added" not in result.stderr, result.stderr
        assert ioc_yaml.read_text() == expected_yaml.read_text(), (
            f"YAML mismatch for {stem}"
        )
        _check_patterns(config, stem)

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


def test_debug(samples: Path):
    """
    A single test to debug the conversion process (a redundant test, just useful
    for launching the debugger against the convert_file function)
    """
    in_xml = samples / "BL99P-EA-IOC-05.xml"
    out_yml = samples / "BL99P-EA-IOC-05.yaml"
    convert_file(in_xml, out_yml, "/epics/ibek-defs/ioc.schema.json")
