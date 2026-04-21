"""
Re-run xml2yaml on every IOC in a beamline's services repo and (optionally)
schema-validate each result with `ibek runtime generate2`. This is the
machine-driven core of the `/beamline-reconvert` slash command: the LLM
handles services-repo resolution and the final human-readable report;
everything between is mechanical and lives here.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from builder2ibek.convert import convert_file

BUILDER_WORK = Path("/dls_sw/work/R3.14.12.7/support")
BUILDER_PROD = Path("/dls_sw/prod/R3.14.12.7/support")

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_SCHEMA = REPO_ROOT / "update-schema"
IOC_SCHEMA = "/epics/ibek-defs/ioc.schema.json"

_SHORT_BL_RE = re.compile(r"^([A-Za-z])([0-9]{1,2})([A-Za-z])?$")


def normalize_beamline(prefix: str) -> str:
    """Canonicalise beamline prefix: 'i21' -> 'BL21I', 'b07' -> 'BL07B',
    'BL19I' -> 'BL19I'."""
    if prefix.upper().startswith("BL"):
        return prefix.upper()
    m = _SHORT_BL_RE.match(prefix)
    if not m:
        raise ValueError(f"cannot parse beamline prefix {prefix!r}")
    letter1, digits, letter2 = m.groups()
    trailing = (letter2 or letter1).upper()
    return f"BL{int(digits):02d}{trailing}"


def discover_xmls(beamline: str) -> tuple[list[Path], Path | None, str]:
    """Return (xmls, source_dir, source) for a normalised beamline prefix.

    Tries the work area first, then the latest version directory in prod.
    """
    work_dir = BUILDER_WORK / f"{beamline}-BUILDER" / "etc" / "makeIocs"
    if work_dir.is_dir():
        xmls = sorted(work_dir.glob("*.xml"))
        if xmls:
            return xmls, work_dir, "work"

    prod_module = BUILDER_PROD / f"{beamline}-BUILDER"
    if prod_module.is_dir():
        versions = sorted(p for p in prod_module.iterdir() if p.is_dir())
        if versions:
            prod_dir = versions[-1] / "etc" / "makeIocs"
            if prod_dir.is_dir():
                xmls = sorted(prod_dir.glob("*.xml"))
                if xmls:
                    return xmls, prod_dir, "prod"

    return [], None, ""


def _is_template_xml(xml: Path) -> bool:
    name = xml.name
    return "$(" in name or "template" in name.lower()


def _read_existing_description(ioc_yaml: Path) -> str:
    if not ioc_yaml.is_file():
        return ""
    try:
        data = YAML(typ="safe").load(ioc_yaml)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get("description") or ""
    return str(value)


@dataclass
class ReconvertResult:
    beamline: str
    services_repo: str
    builder_xml_dir: str | None
    source: str
    xmls_found: int
    validate: bool
    ioc_candidates: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    reconverted: list[dict] = field(default_factory=list)
    conversion_errors: list[dict] = field(default_factory=list)
    validation: list[dict] = field(default_factory=list)


def run_reconvert(
    beamline_prefix: str,
    services_repo: Path,
    *,
    validate: bool = True,
    descriptions: dict[str, str] | None = None,
    only: list[str] | None = None,
) -> tuple[ReconvertResult, int]:
    """Orchestrate discovery, xml2yaml, and optional generate2 validation.

    Exit codes returned: 0 clean, 2 conversion errors, 3 validation failures,
    1 hard failure. ValueError / FileNotFoundError raised for bad input —
    the caller maps those to exit code 1.
    """
    descriptions = descriptions or {}
    only_set = {n.lower() for n in (only or [])}

    beamline = normalize_beamline(beamline_prefix)

    if not services_repo.is_dir():
        raise FileNotFoundError(f"services-repo not found: {services_repo}")

    xmls, source_dir, source = discover_xmls(beamline)
    result = ReconvertResult(
        beamline=beamline,
        services_repo=str(services_repo),
        builder_xml_dir=str(source_dir) if source_dir else None,
        source=source,
        xmls_found=len(xmls),
        validate=validate,
    )

    if not xmls:
        raise FileNotFoundError(f"no BUILDER XMLs found for {beamline} in work or prod")

    services_dir = services_repo / "services"

    for xml in xmls:
        if _is_template_xml(xml):
            result.skipped.append({"xml": str(xml), "reason": "macro-template"})
            continue
        ioc_name = xml.stem.lower()
        services_folder = services_dir / ioc_name
        ioc_yaml = services_folder / "config" / "ioc.yaml"
        if not ioc_yaml.is_file():
            result.skipped.append({"xml": str(xml), "reason": "no-services-folder"})
            continue
        if only_set and ioc_name not in only_set:
            result.skipped.append({"xml": str(xml), "reason": "filtered-by-only"})
            continue
        result.ioc_candidates.append(
            {
                "xml": str(xml),
                "ioc_name": ioc_name,
                "services_folder": str(services_folder),
                "ioc_yaml": str(ioc_yaml),
            }
        )

    for cand in result.ioc_candidates:
        ioc_name = cand["ioc_name"]
        xml = Path(cand["xml"])
        ioc_yaml = Path(cand["ioc_yaml"])
        description = descriptions.get(ioc_name) or _read_existing_description(ioc_yaml)
        try:
            # Route any stray converter prints to stderr so `--json` on
            # stdout stays parseable.
            with contextlib.redirect_stdout(sys.stderr):
                convert_file(xml, ioc_yaml, IOC_SCHEMA, description=description)
            result.reconverted.append({"ioc_name": ioc_name, "status": "ok"})
        except Exception as e:  # noqa: BLE001 — report any converter error
            result.conversion_errors.append(
                {"ioc_name": ioc_name, "error": f"{type(e).__name__}: {e}"}
            )

    if validate and result.reconverted:
        _run_validation(result)

    if result.conversion_errors:
        return result, 2
    if any(v["status"] == "fail" for v in result.validation):
        return result, 3
    return result, 0


def _run_validation(result: ReconvertResult) -> None:
    """Validate each reconverted ioc.yaml with `ibek runtime generate2`.

    One EPICS_ROOT tempdir and one config tempdir are created per
    `reconvert` invocation; the generate2 calls run sequentially inside
    them. CLAUDE.md hard rule 6 (EPICS_ROOT isolation) is satisfied per
    invocation — parallelism is out of scope for this command.
    """
    with (
        tempfile.TemporaryDirectory(prefix="epics-reconvert-") as epics_root,
        tempfile.TemporaryDirectory(prefix="reconvert-config-") as tmp_config,
    ):
        env = os.environ.copy()
        env["EPICS_ROOT"] = epics_root

        schema_proc = subprocess.run(
            [str(UPDATE_SCHEMA)],
            env=env,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if schema_proc.returncode != 0:
            for item in result.reconverted:
                result.validation.append(
                    {
                        "ioc_name": item["ioc_name"],
                        "status": "fail",
                        "stderr": (
                            "update-schema failed: "
                            + (schema_proc.stderr or schema_proc.stdout).strip()
                        ),
                    }
                )
            return

        cfg_ioc = Path(tmp_config) / "ioc.yaml"
        by_name = {c["ioc_name"]: c for c in result.ioc_candidates}
        for item in result.reconverted:
            ioc_name = item["ioc_name"]
            cand = by_name.get(ioc_name)
            if cand is None:
                continue
            shutil.copy(cand["ioc_yaml"], cfg_ioc)
            proc = subprocess.run(
                ["ibek", "runtime", "generate2", "--no-pvi", str(tmp_config)],
                env=env,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                result.validation.append({"ioc_name": ioc_name, "status": "ok"})
            else:
                result.validation.append(
                    {
                        "ioc_name": ioc_name,
                        "status": "fail",
                        "stderr": (proc.stderr or proc.stdout).strip(),
                    }
                )


def _render_human(result: ReconvertResult) -> str:
    lines = [
        f"Beamline:      {result.beamline}",
        f"Services repo: {result.services_repo}",
    ]
    if result.builder_xml_dir:
        lines.append(
            f"Builder XMLs:  {result.xmls_found} ({result.source}: "
            f"{result.builder_xml_dir})"
        )
    lines.append(f"Reconverted:   {len(result.reconverted)}")
    lines.append(f"Skipped:       {len(result.skipped)}")
    lines.append(f"Conversion errors: {len(result.conversion_errors)}")
    if not result.validate:
        lines.append("Validation:    skipped (--no-validate)")
    else:
        passes = sum(1 for v in result.validation if v["status"] == "ok")
        fails = sum(1 for v in result.validation if v["status"] == "fail")
        lines.append(f"Validation:    {passes} pass, {fails} fail")

    if result.conversion_errors:
        lines.append("")
        lines.append("Conversion errors:")
        for err in result.conversion_errors:
            lines.append(f"  - {err['ioc_name']}: {err['error']}")

    failed = [v for v in result.validation if v["status"] == "fail"]
    if failed:
        lines.append("")
        lines.append("Validation failures:")
        for v in failed:
            lines.append(f"  - {v['ioc_name']}:")
            tail = v.get("stderr", "").splitlines()[-5:]
            for line in tail:
                lines.append(f"      {line}")
    return "\n".join(lines)


def reconvert_cli(
    beamline: str,
    services_repo: Path,
    *,
    validate: bool = True,
    descriptions_json: Path | None = None,
    only: list[str] | None = None,
    json_out: bool = False,
) -> None:
    """CLI entry point. Emits human-readable or JSON output and calls
    `sys.exit` with the appropriate code."""
    try:
        descriptions: dict[str, str] | None = None
        if descriptions_json is not None:
            raw = json.loads(Path(descriptions_json).read_text())
            if not isinstance(raw, dict):
                raise ValueError(
                    "--descriptions-json must contain a JSON object "
                    "mapping ioc-name to description"
                )
            descriptions = {str(k).lower(): str(v) for k, v in raw.items()}

        result, exit_code = run_reconvert(
            beamline,
            services_repo,
            validate=validate,
            descriptions=descriptions,
            only=only,
        )
    except (FileNotFoundError, ValueError) as e:
        msg = f"{type(e).__name__}: {e}"
        if json_out:
            print(json.dumps({"error": msg}))
        else:
            print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)

    if json_out:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(_render_human(result))

    sys.exit(exit_code)
