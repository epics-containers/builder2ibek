"""
MCP server exposing builder2ibek tools for both Claude Code and GitHub Copilot.

Run with: uv run fastmcp run mcp_server.py
"""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger(__name__)

mcp = FastMCP(name="builder2ibek")

EPICS_VERSION = "R3.14.12.7"
PROD = f"/dls_sw/prod/{EPICS_VERSION}"
WORK = f"/dls_sw/work/{EPICS_VERSION}"


# --- Helpers (not exposed as tools) ---


def _find_latest_version(module_dir: Path) -> Path | None:
    """Return the latest version directory under a module path, or None."""
    if not module_dir.is_dir():
        return None
    versions = sorted(
        [d for d in module_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.name,
    )
    return versions[-1] if versions else None


def _resolve_release_macros(xml_path: Path) -> dict[str, str]:
    """Parse IOC _RELEASE + BUILDER configure/RELEASE to build module→path table."""
    ioc_name = xml_path.stem.upper()
    release_file = xml_path.parent / f"{ioc_name}_RELEASE"

    if not release_file.is_file():
        # Try without uppercase
        for f in xml_path.parent.glob("*_RELEASE"):
            if f.stem.upper() == f"{ioc_name}_RELEASE".upper():
                release_file = f
                break

    if not release_file.is_file():
        return {}

    # Read _RELEASE lines
    lines = release_file.read_text().splitlines()

    # Find the BUILDER module path to get SUPPORT macro
    builder_path = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        if "BUILDER" in key.upper():
            builder_path = Path(val.strip())
            break

    # Read BUILDER's configure/RELEASE for SUPPORT macro
    support_macro = f"{PROD}/support"
    if builder_path:
        for rel_file in [
            builder_path / "configure" / "RELEASE",
            *builder_path.glob("configure/RELEASE.*.Common"),
        ]:
            if rel_file.is_file():
                for rline in rel_file.read_text().splitlines():
                    rline = rline.strip()
                    if rline.startswith("SUPPORT") and "=" in rline:
                        _, val = rline.split("=", 1)
                        support_macro = val.strip()
                        break
                break

    # Substitute macros and build table
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        key = key.strip()
        val = val.strip()
        # Substitute common macros
        val = val.replace("$(SUPPORT)", support_macro)
        val = val.replace("$(WORK)", WORK)
        val = val.replace("$(EPICS_BASE)", f"{PROD}/base")
        # Module name is typically the key without prefix
        module = key.split("_")[-1] if "_" in key else key
        result[module] = val

    return result


def _find_module_dir(module: str, xml_path: str = "") -> tuple[Path | None, str]:
    """Find module directory. Returns (path, method_used)."""
    # Try _RELEASE resolution first
    if xml_path:
        xml_p = Path(xml_path)
        if xml_p.is_file():
            table = _resolve_release_macros(xml_p)
            for key, val in table.items():
                if key.lower() == module.lower():
                    p = Path(val)
                    if p.is_dir():
                        return p, f"_RELEASE ({key}={val})"

    # Fallback: scan prod
    prod_dir = Path(f"{PROD}/support/{module}")
    latest = _find_latest_version(prod_dir)
    if latest:
        return latest, f"prod latest ({latest})"

    # Fallback: scan work
    work_dir = Path(f"{WORK}/support/{module}")
    latest = _find_latest_version(work_dir)
    if latest:
        return latest, f"work latest ({latest})"

    return None, "not found"


# --- Tools ---


@mcp.tool
def find_module_path(module: str, xml_path: str = "") -> str:
    """Resolve a DLS EPICS support module's absolute filesystem path.

    Args:
        module: Support module name (e.g. 'hidenRGA', 'dlsPLC', 'mks937a')
        xml_path: Optional path to an IOC XML file — if provided, uses the
                  IOC's _RELEASE file for precise version resolution

    Returns:
        The absolute path to the module directory, or an error message.
    """
    path, method = _find_module_dir(module, xml_path)
    if path:
        return f"{path}\n\nResolved via: {method}"
    return f"Module '{module}' not found in {PROD}/support/ or {WORK}/support/"


@mcp.tool
def find_boot_script(ioc_name: str) -> str:
    """Locate and return the original VxWorks .boot file for a DLS IOC.

    Args:
        ioc_name: IOC name (e.g. 'BL19I-VA-IOC-01')

    Returns:
        The boot script content with its path, or an error message.
    """
    # Derive beamline segment
    parts = ioc_name.split("-")
    if len(parts) < 2:
        return (
            f"Cannot derive beamline from '{ioc_name}'"
            " — expected format BLxxX-YY-IOC-NN"
        )
    beamline = parts[0]

    # Check prod ioc area
    ioc_dir = Path(f"{PROD}/ioc/{beamline}/{ioc_name}")
    if ioc_dir.is_dir():
        latest = _find_latest_version(ioc_dir)
        if latest:
            # Search for boot file
            bin_dir = latest / "bin" / "vxWorks-ppc604_long"
            if bin_dir.is_dir():
                boot_files = list(bin_dir.glob("*.boot"))
                if boot_files:
                    boot = boot_files[0]
                    content = boot.read_text()
                    lines = content.splitlines()
                    if len(lines) > 500:
                        header = "\n".join(lines[:500])
                        return (
                            f"# {boot}\n# (first 500 of {len(lines)} lines)\n\n{header}"
                        )
                    return f"# {boot}\n\n{content}"

    # Fallback: work area builder
    builder_name = f"{beamline}-BUILDER"
    work_builder = Path(f"{WORK}/support/{builder_name}")
    if work_builder.is_dir():
        boot_path = work_builder / "iocs" / ioc_name / "cmd" / f"{ioc_name}.boot"
        if boot_path.is_file():
            content = boot_path.read_text()
            return f"# {boot_path}\n\n{content}"
    prod_builder = Path(f"{PROD}/support/{builder_name}")
    latest = _find_latest_version(prod_builder)
    if latest:
        boot_path = latest / "iocs" / ioc_name / "cmd" / f"{ioc_name}.boot"
        if boot_path.is_file():
            content = boot_path.read_text()
            return f"# {boot_path}\n\n{content}"

    return f"Boot script not found for '{ioc_name}' in prod or work areas"


@mcp.tool
def find_ioc_xmls(beamline_prefix: str) -> str:
    """Discover all IOC XML files for a DLS beamline.

    Args:
        beamline_prefix: Beamline prefix (e.g. 'BL19I', 'BL04I', 'SR03C')

    Returns:
        List of IOC XML paths, one per line. Template XMLs are excluded.
    """
    bl = beamline_prefix.upper()
    builder_name = f"{bl}-BUILDER"

    xml_files: list[Path] = []

    # Check work area first
    work_path = Path(f"{WORK}/support/{builder_name}/etc/makeIocs")
    if work_path.is_dir():
        xml_files = sorted(work_path.glob("*.xml"))
    else:
        # Fallback to prod (latest version)
        prod_dir = Path(f"{PROD}/support/{builder_name}")
        latest = _find_latest_version(prod_dir)
        if latest:
            make_iocs = latest / "etc" / "makeIocs"
            if make_iocs.is_dir():
                xml_files = sorted(make_iocs.glob("*.xml"))

    if not xml_files:
        return f"No IOC XMLs found for {builder_name} in work or prod areas"

    # Filter out template XMLs (contain $(macro) syntax)
    result = []
    templates = []
    for f in xml_files:
        try:
            content = f.read_text(errors="replace")
            if "$(" in content and re.search(r"\$\(\w+\)", content):
                templates.append(f.name)
            else:
                result.append(str(f))
        except OSError:
            continue

    output = f"# IOC XMLs for {bl} ({len(result)} IOCs)\n\n"
    output += "\n".join(result)
    if templates:
        output += f"\n\n# Excluded templates: {', '.join(templates)}"
    return output


@mcp.tool
def support_inspect(module: str) -> str:
    """Analyze a DLS EPICS support module's builder.py.

    Extracts classes, parameters, database templates, st.cmd commands,
    install requirements, and dependencies. Returns raw structured data
    for AI interpretation.

    Args:
        module: Support module name (e.g. 'hidenRGA', 'dlsPLC')

    Returns:
        Markdown report with sections for each discovered class.
    """
    path, method = _find_module_dir(module)
    if not path:
        return f"Module '{module}' not found"

    report = [
        f"# {module} — support inspection",
        f"\nPath: `{path}` (resolved via {method})\n",
    ]

    # Read all Python files in etc/
    etc_dir = path / "etc"
    py_files: list[Path] = []
    if etc_dir.is_dir():
        py_files = sorted(etc_dir.glob("*.py"))

    if not py_files:
        report.append("No Python files found in etc/")
        return "\n".join(report)

    report.append("## Python source files\n")
    for f in py_files:
        report.append(f"- `{f.name}`")

    # Read and analyze each file
    for py_file in py_files:
        content = py_file.read_text(errors="replace")
        report.append(f"\n## {py_file.name}\n")

        # Extract classes
        class_pattern = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.MULTILINE)
        for match in class_pattern.finditer(content):
            cls_name, bases = match.group(1), match.group(2)
            report.append(f"### Class: `{cls_name}` (bases: `{bases}`)")

            # Check for skip indicators
            # Look for AutoInstantiate or BaseClass
            after_class = content[match.end() : match.end() + 500]
            if re.search(r"AutoInstantiate\s*=\s*True", after_class):
                report.append("*AutoInstantiate — singleton, skip*\n")
                continue
            if re.search(r"BaseClass\s*=\s*True", after_class):
                report.append("*BaseClass — abstract, skip*\n")
                continue

            # TemplateFile
            tf_match = re.search(r"TemplateFile\s*=\s*['\"]([^'\"]+)['\"]", after_class)
            if tf_match:
                report.append(f"- TemplateFile: `{tf_match.group(1)}`")

            # DbdFileList, LibFileList, ProtocolFiles
            for attr in ["DbdFileList", "LibFileList", "ProtocolFiles"]:
                attr_match = re.search(rf"{attr}\s*=\s*\[([^\]]*)\]", after_class)
                if attr_match:
                    report.append(f"- {attr}: `[{attr_match.group(1).strip()}]`")

            # Dependencies
            dep_match = re.search(r"Dependencies\s*=\s*\(([^)]*)\)", after_class)
            if dep_match:
                report.append(f"- Dependencies: `({dep_match.group(1).strip()})`")

            report.append("")

        # Extract ArgInfo blocks
        arginfo_pattern = re.compile(
            r"(\w+)\s*=\s*makeArgInfo\s*\(\s*__init__\s*,([^)]*)\)", re.MULTILINE
        )
        arginfos = list(arginfo_pattern.finditer(content))
        if arginfos:
            report.append("### ArgInfo declarations\n")
            for m in arginfos:
                report.append(
                    f"- `{m.group(1)}`: `makeArgInfo(__init__, {m.group(2).strip()})`"
                )
            report.append("")

        # Extract Initialise methods
        init_pattern = re.compile(
            r"def\s+(Initialise(?:Once)?|PostIocInitialise|Initialise_\w+)\s*\(self\)",
            re.MULTILINE,
        )
        for m in init_pattern.finditer(content):
            method_name = m.group(1)
            # Get method body (next ~20 lines)
            start = m.end()
            lines = content[start : start + 1500].splitlines()
            body_lines = []
            for line in lines[1:]:  # skip the colon line
                if line.strip() and not line[0].isspace() and not line.startswith(" "):
                    break
                body_lines.append(line)
                if len(body_lines) > 20:
                    body_lines.append("        ...")
                    break
            report.append(f"### {method_name}\n```python")
            report.extend(body_lines)
            report.append("```\n")

    # Read db macros
    db_dir = path / "db"
    if db_dir.is_dir():
        db_files = sorted(db_dir.glob("*.db")) + sorted(db_dir.glob("*.template"))
        if db_files:
            report.append("## Database templates\n")
            for db_file in db_files:
                macros = []
                try:
                    for line in db_file.read_text(errors="replace").splitlines():
                        if line.startswith("# % macro"):
                            macros.append(line)
                except OSError:
                    continue
                if macros:
                    report.append(f"### `{db_file.name}`\n")
                    for m in macros:
                        report.append(f"- {m}")
                    report.append("")

    # Find example IOC usage
    report.append("## Example IOC usage\n")
    try:
        import subprocess

        result = subprocess.run(
            ["grep", "-rl", module, f"{WORK}/support/"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        xml_hits = [
            line
            for line in result.stdout.splitlines()
            if line.endswith(".xml") and "makeIocs" in line
        ][:5]
        if xml_hits:
            for hit in xml_hits:
                report.append(f"- `{hit}`")
        else:
            report.append("No example IOCs found in work area")
    except Exception:
        report.append("Could not search for examples")

    return "\n".join(report)


@mcp.tool
def ioc_inspect(xml_path: str) -> str:
    """Parse a DLS IOC XML file and report its structure.

    Shows which support modules and entity types are used, with counts
    and attribute summaries.

    Args:
        xml_path: Path to the IOC XML file

    Returns:
        Markdown report of the IOC structure.
    """
    from builder2ibek.builder import Builder

    p = Path(xml_path)
    if not p.is_file():
        return f"File not found: {xml_path}"

    builder = Builder()
    try:
        builder.load(p)
    except Exception as e:
        return f"Failed to parse XML: {e}"

    report = [
        f"# {builder.name}",
        f"\nArchitecture: `{builder.arch}`",
        f"Elements: {len(builder.elements)}\n",
    ]

    # Group by module
    by_module: dict[str, list] = defaultdict(list)
    for elem in builder.elements:
        by_module[elem.module].append(elem)

    report.append("## Modules\n")
    for mod in sorted(by_module.keys()):
        elems = by_module[mod]
        report.append(f"### {mod} ({len(elems)} entities)\n")

        # Group by entity type within module
        by_type: dict[str, list] = defaultdict(list)
        for e in elems:
            by_type[e.name].append(e)

        for etype in sorted(by_type.keys()):
            instances = by_type[etype]
            disabled = sum(
                1
                for e in instances
                if e.attributes.get("disabled", "").lower() == "true"
            )
            suffix = f" ({disabled} disabled)" if disabled else ""
            report.append(f"- **{etype}** x{len(instances)}{suffix}")

            # Show attribute names from first instance
            if instances:
                attrs = sorted(instances[0].attributes.keys())
                # Filter out common noise
                attrs = [a for a in attrs if a not in ("disabled",)]
                if attrs:
                    report.append(f"  - Attributes: {', '.join(attrs)}")

        report.append("")

    return "\n".join(report)
