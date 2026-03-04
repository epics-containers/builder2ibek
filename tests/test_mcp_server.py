"""Tests for MCP server tool functions."""

import re
from pathlib import Path

import pytest
from mcp_server import (
    _find_latest_version,
    _find_module_dir,
    find_boot_script,
    find_ioc_xmls,
    find_module_path,
    ioc_inspect,
    support_inspect,
)

SAMPLES = Path(__file__).parent / "samples"
HAS_DLS = Path("/dls_sw").exists()
skip_no_dls = pytest.mark.skipif(not HAS_DLS, reason="DLS filesystem required")


class TestIocInspect:
    """ioc_inspect works with local sample XMLs — no DLS filesystem needed."""

    def test_basic_parse(self):
        xml = SAMPLES / "BL04I-VA-IOC-01.xml"
        result = ioc_inspect(str(xml))
        assert "# BL04I-VA-IOC-01" in result
        assert "## Modules" in result

    def test_reports_modules(self):
        xml = SAMPLES / "BL04I-VA-IOC-01.xml"
        result = ioc_inspect(str(xml))
        # Should find at least one module
        assert "###" in result

    def test_reports_entity_counts(self):
        xml = SAMPLES / "BL04I-MO-IOC-03.xml"
        result = ioc_inspect(str(xml))
        # Should have entity counts like "x3"
        assert re.search(r"x\d+", result)

    def test_missing_file(self):
        result = ioc_inspect("/nonexistent/file.xml")
        assert "not found" in result.lower()

    def test_all_samples_parse(self):
        """All sample XMLs should parse without errors."""
        for xml in sorted(SAMPLES.glob("*.xml")):
            result = ioc_inspect(str(xml))
            assert result.startswith("#"), f"Failed to parse {xml.name}: {result}"


class TestFindModulePath:
    @skip_no_dls
    def test_known_module(self):
        result = find_module_path("hidenRGA")
        assert "/dls_sw/" in result
        assert "hidenRGA" in result

    @skip_no_dls
    def test_with_xml(self):
        xml = SAMPLES / "BL04I-VA-IOC-01.xml"
        result = find_module_path("vacuumSpace", str(xml))
        # Should resolve to a path
        assert "/dls_sw/" in result or "not found" in result.lower()

    def test_nonexistent_module(self):
        result = find_module_path("nonexistent_module_xyz")
        assert "not found" in result.lower()


class TestFindBootScript:
    @skip_no_dls
    def test_known_ioc(self):
        result = find_boot_script("BL04I-VA-IOC-01")
        # Either finds content or says not found
        assert len(result) > 0

    def test_bad_format(self):
        result = find_boot_script("nope")
        assert "cannot derive" in result.lower()


class TestFindIocXmls:
    @skip_no_dls
    def test_known_beamline(self):
        result = find_ioc_xmls("BL04I")
        assert "IOC XMLs" in result

    def test_nonexistent_beamline(self):
        result = find_ioc_xmls("BLZZZ")
        assert "not found" in result.lower() or "No IOC XMLs" in result


class TestSupportInspect:
    @skip_no_dls
    def test_known_module(self):
        result = support_inspect("hidenRGA")
        assert "# hidenRGA" in result
        assert "Python source files" in result or "No Python files" in result

    def test_nonexistent_module(self):
        result = support_inspect("nonexistent_module_xyz")
        assert "not found" in result.lower()


class TestHelpers:
    def test_find_latest_version_nonexistent(self):
        result = _find_latest_version(Path("/nonexistent"))
        assert result is None

    def test_find_module_dir_nonexistent(self):
        path, method = _find_module_dir("nonexistent_module_xyz")
        assert path is None
        assert "not found" in method
