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

An IOC that is live but has no redirect entry cannot boot, so it is skipped;
the report shows its newest build under ``/dls_sw/prod/<epics>/ioc/<PREFIX>/``.

The IOCs keep running on their IOC servers. Stop an IOC on its server first,
then deploy and start its folder's cluster copy: with hostNetwork two running
copies would serve the same PVs. The plan output and each values.yaml say so. Deploying
is done outside builder2ibek (``ec`` or the deployment repo).

Nothing here writes outside the services repo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML

from builder2ibek.reconvert import normalize_beamline

DLS_SW = Path("/dls_sw")
INIT_DIR = DLS_SW / "prod/etc/init"
REDIRECT_TABLE = DLS_SW / "prod/etc/redirector/redirect_table"
DEFAULT_EPICS = "R3.14.12.7"
TEMPLATE = ".legacy_ioc_template"
PLACEHOLDER_RE = re.compile(r"^([ \t]*)iocVersion:.*REPLACE.*$", re.MULTILINE)

# Launch-list entries that start a service rather than an IOC (from the
# DLS-wide server sweep).
NON_IOC_SCRIPT_RE = re.compile(
    r"(scanner|stOdinServer|stFrameReceiver\d+|stFrameProcessor\d+|stMetaWriter"
    r"|stEigerFan|stControlServer|stLiveViewMerge)\.sh"
)
MANUALSTART_NOTE = "manualstart: keep stopped after deploying"
WARNING = """\
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
WARNING: these IOCs still run on their IOC servers.
Cut over one IOC at a time: stop the IOC on its server first, then deploy
and start its cluster copy (ec start --commit <service>). With hostNetwork,
two running copies would serve the same PVs. If a service has to be deployed
before that, deploy it stopped (ec stop --commit <service> immediately),
knowing that both copies serve the same PVs for that short window.
IOCs marked manualstart: keep stopped after deploying.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"""
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
    args: list[str] = field(default_factory=list)  # after the port


@dataclass
class PlanEntry:
    ioc: str
    folder: str
    action: str  # add or skip
    reason: str = ""
    version: str = ""
    source: str = ""  # redirector or none
    source_ref: str = ""  # file:line the boot script was read from
    boot: str = ""
    servers: list[str] = field(default_factory=list)
    values: dict[str, object] = field(default_factory=dict)
    manualstart: bool = False  # normally stopped on its server
    header: str = ""  # warning comment for the top of values.yaml
    notes: list[str] = field(default_factory=list)


@dataclass
class Plan:
    prefix: str
    services_repo: str
    location: str
    sources: list[str]
    entries: list[PlanEntry] = field(default_factory=list)
    retired: list[dict[str, str]] = field(default_factory=list)


def read_redirect_table(path: Path) -> dict[str, list[tuple[str, str]]]:
    """IOC name -> every (boot script, file:line) for it, in file order.
    The redirector uses the first."""
    table: dict[str, list[tuple[str, str]]] = {}
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        fields = line.split()
        if len(fields) < 2 or line.startswith("#"):
            continue
        table.setdefault(fields[0], []).append((fields[1], f"{path}:{lineno}"))
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
                # soft-iocs: IOC PORT [args]; real-iocs: IOC HOST PORT [args]
                extra = fields[2 if kind == "soft-iocs" else 3 :]
                entries.setdefault(fields[0], []).append(
                    LaunchEntry(
                        server=path.parent.name,
                        kind=kind,
                        source=f"{path}:{lineno}",
                        manualstart="manualstart" in extra,
                        args=[a for a in extra if a != "manualstart"],
                    )
                )
    return entries


def _version_key(version: str) -> tuple:
    """Sort key for a DLS release: only whole ``-``/``.``-separated tokens
    count as numbers, so the R7 in ``2020-R7-Run2-2`` is text."""
    tokens = re.split(r"[-.]", version)
    return tuple((1, int(t), "") if t.isdigit() else (0, 0, t) for t in tokens)


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
        notes.append("runs from /dls_sw/work: needs a release")
    else:
        version = "work" if boot.startswith("/dls_sw/work/") else ""
        _explicit_entrypoint(boot, values)
        notes.append("non-standard entrypoint: workingDir and args set, review")
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
    init_dir: Path | None = None,
    redirect_table: Path | None = None,
    dls_sw: Path = DLS_SW,
) -> Plan:
    """Plan the folders. ``init_dir`` and ``redirect_table`` default to their
    place under ``dls_sw``."""
    prefix = normalize_beamline(prefix)
    init_dir = init_dir or dls_sw / INIT_DIR.relative_to(DLS_SW)
    redirect_table = redirect_table or dls_sw / REDIRECT_TABLE.relative_to(DLS_SW)
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
        boot, ref = redirect[ioc][0]
        plan.retired.append({"ioc": ioc, "boot": boot, "source": ref})

    for ioc in sorted(name for name in launches if ours(name)):
        entry = PlanEntry(ioc=ioc, folder=ioc.lower(), action="skip")
        entry.servers = [
            f"{e.server} ({e.kind}{', manualstart' if e.manualstart else ''})"
            for e in launches[ioc]
        ]
        plan.entries.append(entry)
        for launch in launches[ioc]:
            if launch.args:
                entry.notes.append(
                    f"launch arguments on {launch.server}: {' '.join(launch.args)}"
                )

        if ioc in redirect:
            entry.boot, entry.source_ref = redirect[ioc][0]
            entry.source = "redirector"
            if len(redirect[ioc]) > 1:
                lines = ", ".join(ref.rsplit(":", 1)[1] for _, ref in redirect[ioc])
                entry.notes.append(
                    f"duplicate redirect entries (lines {lines}): the first is used;"
                    " a duplicate breaks the boot on Linux, fix the table"
                )
        else:
            entry.source = "none"
            newest = newest_build(ioc, prefix, dls_sw)
            entry.notes.append(f"newest build: {newest or 'none in /dls_sw/prod'}")

        folder = services / entry.folder
        if os.path.lexists(folder):
            entry.reason = f"services folder exists ({_folder_kind(folder)})"
            continue
        if not entry.boot:
            entry.reason = "in launch list but no redirect entry, so it cannot boot"
            continue
        reason = _classify_os(entry.boot)
        if reason:
            entry.reason = reason
            continue
        if not _local(entry.boot, dls_sw).exists():
            entry.reason = f"boot script missing: {entry.boot}"
            continue

        entry.values, entry.version, notes = derive_values(
            ioc, entry.boot, location, dls_sw
        )
        entry.notes.extend(notes)
        if entry.version == "work":
            released = newest_build(ioc, prefix, dls_sw)
            match = PROD_RE.match(released or "")
            entry.notes.append(
                f"newest prod build is {match['version']}"
                if match
                else "no prod build yet"
            )
        servers = ", ".join(e.server for e in launches[ioc])
        entry.manualstart = any(e.manualstart for e in launches[ioc])
        entry.header = (
            f"WARNING: this IOC still runs on {servers}. Stop it there first,"
            " then deploy and start this service: with hostNetwork both would"
            " serve the same PVs. If it has to be deployed before that, deploy"
            f" it stopped (ec stop --commit {entry.folder} immediately); both"
            " serve the same PVs for that short window."
        )
        if entry.manualstart:
            entry.notes.append(MANUALSTART_NOTE)
            entry.header += f" {MANUALSTART_NOTE[0].upper()}{MANUALSTART_NOTE[1:]}."
        entry.action = "add"
    return plan


def _scalar(value: object) -> str:
    """A YAML scalar that loads back as the same string."""
    text = str(value)
    loaded = YAML(typ="safe").load(text)
    return text if loaded == text and ":" not in text else json.dumps(text)


def render_values(template: str, values: dict[str, object], header: str = "") -> str:
    """Replace the template's iocVersion placeholder with ``values``,
    keeping every comment. ``header`` becomes a comment at the top, after
    any yaml-language-server modeline."""
    if header:
        comment = "".join(f"# {line}\n" for line in textwrap.wrap(header, 76))
        first, nl, rest = template.partition("\n")
        if first.startswith("# yaml-language-server"):
            template = f"{first}{nl}{comment}{rest}"
        else:
            template = comment + template
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
    """Write the planned folders. Every target is checked for existence (as a
    file, folder or dangling link) before any write, and nothing is written
    if one exists. An I/O error part way through leaves the folders written
    so far; a re-run skips them."""
    services = Path(plan.services_repo) / "services"
    template = services / TEMPLATE
    if not (template / "values.yaml").is_file():
        raise FileNotFoundError(f"{template}/values.yaml not found")
    template_text = (template / "values.yaml").read_text()
    adds = [e for e in plan.entries if e.action == "add"]
    rendered = {
        e.folder: render_values(template_text, e.values, e.header) for e in adds
    }
    clashes = [e.folder for e in adds if os.path.lexists(services / e.folder)]
    if clashes:
        raise FileExistsError(
            f"nothing written: already in {services}: {', '.join(clashes)}"
        )
    written: list[Path] = []
    for entry in adds:
        dest = services / entry.folder
        shutil.copytree(template, dest, symlinks=True)
        (dest / "values.yaml").write_text(rendered[entry.folder])
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
            if e.manualstart:
                detail = f"[{MANUALSTART_NOTE}] {detail}"
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
    out += ["", f"{adds} folder(s) {verb}", "", WARNING]
    return "\n".join(out)


def devc7_cli(
    prefix: str,
    services_repo: Path,
    *,
    apply: bool = False,
    json_out: bool = False,
    init_dir: Path | None = None,
    redirect_table: Path | None = None,
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
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_out:
        print(json.dumps(asdict(plan), indent=2))
    else:
        print(render_plan(plan, apply))
    return 0
