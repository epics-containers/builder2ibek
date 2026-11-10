"""
Plan, and optionally write, dev-c7 legacy services folders for every live
Linux IOC of a beamline prefix.

A dev-c7 folder runs the IOC's traditional /dls_sw build inside the cluster.
It is phase 1 of a beamline migration; phase 2 converts each IOC to ibek,
which replaces its legacy folder.

The version each IOC runs comes from the two files the DLS IOC servers boot
from:

- the init launch lists, ``<init-dir>/<server>/soft-iocs`` (``IOC PORT
  [manualstart]``) and ``<init-dir>/<server>/real-iocs`` (``IOC HOST PORT``,
  the console of a hardware IOC). An IOC listed in either is live.
- the redirect table, ``<redirector>/redirect_table`` (``IOC BOOT-SCRIPT``).
  The redirector takes the first line whose first field is the IOC name.

An IOC that is live but has no redirect entry falls back to its newest build
under ``/dls_sw/prod/<epics>/ioc/<PREFIX>/<IOC>/``.

Nothing here writes outside the services repo.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML

from builder2ibek.reconvert import normalize_beamline

DLS_SW = Path("/dls_sw")
INIT_DIR = DLS_SW / "prod/etc/init"
REDIRECT_TABLE = DLS_SW / "prod/etc/redirector/redirect_table"
DEFAULT_EPICS = "R3.14.12.7"
TEMPLATE = ".legacy_ioc_template"
PLACEHOLDER_RE = re.compile(r"^(\s*)iocVersion:.*REPLACE.*$", re.MULTILINE)

# Launch-list entries that start a service rather than an IOC (from the
# DLS-wide server sweep).
NON_IOC_SCRIPT_RE = re.compile(
    r"(scanner|stOdinServer|stFrameReceiver\d+|stFrameProcessor\d+|stMetaWriter"
    r"|stEigerFan|stControlServer|stLiveViewMerge)\.sh"
)
PROD_RE = re.compile(
    r"^/dls_sw/prod/(?P<epics>[^/]+)/ioc/(?P<domain>[^/]+)/(?P<name>[^/]+)"
    r"/(?P<version>[^/]+)/(?P<rest>.+)$"
)
WORK_RE = re.compile(
    r"^(?P<ioc_path>/dls_sw/work/.+)/(?P<name>[^/]+)/bin/linux-x86_64/(?P<script>[^/]+)$"
)
ARCH_RE = re.compile(r"/bin/(?P<arch>[^/]+)/[^/]+$")


@dataclass
class LaunchEntry:
    server: str
    kind: str  # soft-iocs or real-iocs
    source: str  # file:line
    manualstart: bool = False


@dataclass
class PlanEntry:
    ioc: str
    folder: str
    action: str  # add or skip
    reason: str = ""
    version: str = ""
    source: str = ""  # redirector, newest-build or none
    source_ref: str = ""  # file:line the boot script was read from
    boot: str = ""
    servers: list[str] = field(default_factory=list)
    values: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Plan:
    prefix: str
    services_repo: str
    location: str
    sources: list[str]
    entries: list[PlanEntry] = field(default_factory=list)
    retired: list[dict[str, str]] = field(default_factory=list)


def read_redirect_table(path: Path) -> dict[str, tuple[str, str]]:
    """IOC name -> (boot script, file:line). The first entry wins."""
    table: dict[str, tuple[str, str]] = {}
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        fields = line.split()
        if len(fields) < 2 or line.startswith("#"):
            continue
        table.setdefault(fields[0], (fields[1], f"{path}:{lineno}"))
    return table


def read_init(init_dir: Path) -> dict[str, list[LaunchEntry]]:
    """IOC name -> every launch-list entry that names it."""
    entries: dict[str, list[LaunchEntry]] = {}
    for kind in ("soft-iocs", "real-iocs"):
        for path in sorted(init_dir.glob(f"*/{kind}")):
            text = path.read_text(errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                fields = line.split("#", 1)[0].split()
                if not fields:
                    continue
                entries.setdefault(fields[0], []).append(
                    LaunchEntry(
                        server=path.parent.name,
                        kind=kind,
                        source=f"{path}:{lineno}",
                        manualstart="manualstart" in fields[1:],
                    )
                )
    return entries


def _version_key(version: str) -> tuple:
    return (tuple(int(n) for n in re.findall(r"\d+", version)), version)


def _local(path: str, dls_sw: Path) -> Path:
    """Map a /dls_sw path to the dls_sw root in use."""
    return dls_sw / PurePosixPath(path).relative_to("/dls_sw")


def newest_build(ioc: str, domain: str, dls_sw: Path) -> str | None:
    """The boot script of the newest built version of ``ioc`` in prod."""
    found: list[tuple[tuple, str, str]] = []
    for script in (dls_sw / "prod").glob(f"*/ioc/{domain}/{ioc}/*/bin/*/st{ioc}*"):
        version_dir = script.parents[2]
        epics = version_dir.parents[3].name
        arch_rank = "1" if script.parent.name == "linux-x86_64" else "0"
        found.append(
            (
                _version_key(version_dir.name),
                epics + arch_rank,
                f"/dls_sw/{script.relative_to(dls_sw).as_posix()}",
            )
        )
    return max(found)[2] if found else None


def _classify_os(boot: str) -> str | None:
    """A reason the boot script can't run in a RHEL7 container, or None."""
    match = ARCH_RE.search(boot)
    suffix = PurePosixPath(boot).suffix.lower()
    arch = match["arch"] if match else ""
    if arch.startswith(("windows", "win32")) or suffix in (".bat", ".cmd"):
        return f"Windows IOC ({arch or suffix})"
    if arch.startswith("vxWorks"):
        return f"vxWorks IOC ({arch})"
    if arch.startswith("RTEMS"):
        return f"RTEMS IOC ({arch})"
    if arch and arch != "linux-x86_64":
        return f"{arch} target, not runnable in an x86_64 RHEL7 container"
    if suffix in (".yaml", ".yml"):
        return "Malcolm YAML definition, not an IOC startup script"
    if NON_IOC_SCRIPT_RE.fullmatch(PurePosixPath(boot).name):
        return f"non-IOC service ({PurePosixPath(boot).name})"
    if not boot.startswith(("/dls_sw/prod/", "/dls_sw/work/")):
        return "boot script outside /dls_sw/prod and /dls_sw/work"
    return None


def _default_glob_ok(boot: str, ioc: str, dls_sw: Path) -> bool:
    """True when the chart's default ``./bin/linux-x86_64/st*.sh`` finds
    exactly this IOC's own startup script."""
    if PurePosixPath(boot).name != f"st{ioc}.sh":
        return False
    bin_dir = _local(boot, dls_sw).parent
    if not bin_dir.is_dir():
        return True  # can't check; the layout is the standard one
    return [p.name for p in bin_dir.glob("st*.sh")] == [f"st{ioc}.sh"]


def _explicit_entrypoint(boot: str, values: dict[str, object]) -> None:
    """Point workingDir and args straight at the boot script."""
    path = PurePosixPath(boot)
    if "bin" in path.parts:
        idx = len(path.parts) - 1 - path.parts[::-1].index("bin")
        working = PurePosixPath(*path.parts[:idx])
    else:
        working = path.parent
    values["workingDir"] = str(working)
    values["args"] = [f"stdio-expose ./{path.relative_to(working)}"]


def derive_values(
    ioc: str, boot: str, location: str, dls_sw: Path
) -> tuple[dict[str, object], str, list[str]]:
    """(dev-c7 values, version, notes) for a Linux boot script."""
    values: dict[str, object] = {}
    notes: list[str] = []
    prod = PROD_RE.match(boot)
    work = WORK_RE.match(boot)
    if prod:
        version = prod["version"]
        values["iocVersion"] = version
        if prod["domain"].upper() != location.upper():
            values["epicsDomain"] = prod["domain"].upper()
        if prod["epics"] != DEFAULT_EPICS:
            values["epicsVersion"] = prod["epics"]
        standard = (
            prod["name"] == ioc
            and prod["rest"] == f"bin/linux-x86_64/st{ioc}.sh"
            and _default_glob_ok(boot, ioc, dls_sw)
        )
        if not standard:
            values.clear()
            _explicit_entrypoint(boot, values)
            notes.append("non-standard entrypoint: workingDir and args set, review")
    elif work and work["name"] == ioc and _default_glob_ok(boot, ioc, dls_sw):
        version = "work"
        values["iocPath"] = work["ioc_path"]
        notes.append("runs from /dls_sw/work, not a released version")
    else:
        version = "work" if boot.startswith("/dls_sw/work/") else ""
        _explicit_entrypoint(boot, values)
        notes.append("non-standard entrypoint: workingDir and args set, review")
    if not _local(boot, dls_sw).exists():
        notes.append(f"boot script not found: {boot}")
    return values, version, notes


def _folder_kind(folder: Path) -> str:
    values = folder / "values.yaml"
    if values.is_file() and re.search(r"^dev-c7:", values.read_text(), re.MULTILINE):
        return "dev-c7 legacy"
    if (folder / "config" / "ioc.yaml").is_file():
        return "ibek"
    return "other"


def read_location(services_repo: Path) -> str:
    values = services_repo / "services" / "values.yaml"
    if not values.is_file():
        return ""
    data = YAML(typ="safe").load(values.read_text()) or {}
    return str((data.get("global") or {}).get("location") or "")


def build_plan(
    prefix: str,
    services_repo: Path,
    *,
    init_dir: Path = INIT_DIR,
    redirect_table: Path = REDIRECT_TABLE,
    dls_sw: Path = DLS_SW,
) -> Plan:
    prefix = normalize_beamline(prefix)
    redirect = read_redirect_table(redirect_table)
    launches = read_init(init_dir)
    location = read_location(services_repo)
    services = services_repo / "services"

    def ours(name: str) -> bool:
        return name.startswith(f"{prefix}-")

    plan = Plan(
        prefix=prefix,
        services_repo=str(services_repo),
        location=location,
        sources=[
            str(redirect_table),
            f"{init_dir}/*/soft-iocs",
            f"{init_dir}/*/real-iocs",
        ],
    )

    for ioc in sorted(name for name in redirect if ours(name) and name not in launches):
        plan.retired.append(
            {"ioc": ioc, "boot": redirect[ioc][0], "source": redirect[ioc][1]}
        )

    for ioc in sorted(name for name in launches if ours(name)):
        entry = PlanEntry(ioc=ioc, folder=ioc.lower(), action="skip")
        entry.servers = [
            f"{e.server} ({e.kind}{', manualstart' if e.manualstart else ''})"
            for e in launches[ioc]
        ]
        plan.entries.append(entry)

        if ioc in redirect:
            entry.boot, entry.source_ref = redirect[ioc]
            entry.source = "redirector"
        else:
            entry.boot = newest_build(ioc, prefix, dls_sw) or ""
            entry.source = "newest-build" if entry.boot else "none"
            entry.source_ref = entry.boot
            entry.notes.append("not in the redirect table")

        folder = services / entry.folder
        if folder.exists():
            entry.reason = f"services folder exists ({_folder_kind(folder)})"
            continue
        if not entry.boot:
            entry.reason = "not in the redirect table and no build in /dls_sw/prod"
            continue
        reason = _classify_os(entry.boot)
        if reason:
            entry.reason = reason
            continue

        entry.values, entry.version, notes = derive_values(
            ioc, entry.boot, location, dls_sw
        )
        entry.notes.extend(notes)
        if entry.version == "work":
            released = newest_build(ioc, prefix, dls_sw)
            match = PROD_RE.match(released or "")
            if match:
                entry.notes.append(f"newest prod build is {match['version']}")
        manual = [e.server for e in launches[ioc] if e.manualstart]
        if manual:
            entry.notes.append(f"manualstart on {', '.join(manual)}")
        entry.action = "add"
    return plan


def _scalar(value: object) -> str:
    """A YAML scalar that loads back as the same string."""
    text = str(value)
    loaded = YAML(typ="safe").load(text)
    return text if loaded == text and ":" not in text else json.dumps(text)


def render_values(template: str, values: dict[str, object]) -> str:
    """Replace the template's iocVersion placeholder with ``values``,
    keeping every comment."""
    lines: list[str] = []
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {_scalar(v)}" for v in value)
        else:
            lines.append(f"{key}: {_scalar(value)}")

    match = PLACEHOLDER_RE.search(template)
    if match:
        indent = match[1]
        block = "\n".join(indent + line for line in lines)
        return template[: match.start()] + block + template[match.end() :]
    head, sep, tail = template.partition("dev-c7:\n")
    if not sep:
        raise ValueError(f"no dev-c7: key in {TEMPLATE}/values.yaml")
    return head + sep + "".join(f"  {line}\n" for line in lines) + tail


def apply_plan(plan: Plan) -> list[Path]:
    services = Path(plan.services_repo) / "services"
    template = services / TEMPLATE
    if not (template / "values.yaml").is_file():
        raise FileNotFoundError(f"{template}/values.yaml not found")
    template_text = (template / "values.yaml").read_text()
    written: list[Path] = []
    for entry in plan.entries:
        if entry.action != "add":
            continue
        dest = services / entry.folder
        if dest.exists():  # never overwrite
            entry.action, entry.reason = "skip", "services folder appeared"
            continue
        shutil.copytree(template, dest, symlinks=True)
        (dest / "values.yaml").write_text(render_values(template_text, entry.values))
        written.append(dest)
    return written


def render_plan(plan: Plan, applied: bool) -> str:
    out = [
        f"dev-c7 plan for {plan.prefix} -> {plan.services_repo}"
        f" (global.location: {plan.location or 'unset'})",
        "sources: " + ", ".join(plan.sources),
        "",
    ]
    rows = [("IOC", "ACTION", "VERSION", "SOURCE", "DETAIL")]
    for e in plan.entries:
        if e.action == "add":
            detail = ", ".join(f"{k}={v}" for k, v in e.values.items())
        else:
            detail = e.reason
        rows.append((e.ioc, e.action, e.version or "-", e.source, detail))
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for row in rows:
        out.append(
            "  ".join(c.ljust(w) for c, w in zip(row[:4], widths, strict=True))
            + "  "
            + row[4]
        )
    notes = [(e.ioc, n) for e in plan.entries for n in e.notes]
    if notes:
        out += ["", "notes:"] + [f"  {ioc}: {n}" for ioc, n in notes]
    out += ["", "launched from:"]
    out += [f"  {e.ioc}: {'; '.join(e.servers)}" for e in plan.entries]
    if plan.retired:
        out += ["", "retired (in the redirect table, in no launch list), left out:"]
        out += [f"  {r['ioc']}: {r['boot']}" for r in plan.retired]
    adds = sum(e.action == "add" for e in plan.entries)
    verb = "added" if applied else "to add (dry run; --apply writes them)"
    out += ["", f"{adds} folder(s) {verb}"]
    return "\n".join(out)


def devc7_cli(
    prefix: str,
    services_repo: Path,
    *,
    apply: bool = False,
    json_out: bool = False,
    init_dir: Path = INIT_DIR,
    redirect_table: Path = REDIRECT_TABLE,
    dls_sw: Path = DLS_SW,
) -> int:
    if not (services_repo / "services").is_dir():
        print(f"error: {services_repo}/services not found", file=sys.stderr)
        return 1
    try:
        plan = build_plan(
            prefix,
            services_repo,
            init_dir=init_dir,
            redirect_table=redirect_table,
            dls_sw=dls_sw,
        )
        if apply:
            apply_plan(plan)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_out:
        print(json.dumps(asdict(plan), indent=2))
    else:
        print(render_plan(plan, apply))
    return 0
