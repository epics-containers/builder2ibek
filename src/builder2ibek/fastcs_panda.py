"""
ADPandABlocks IOCs become fastcs-pandablocks service instances.

fastcs-pandablocks introspects the PandA itself, so a PandA needs only its PV
prefix and its box address. builder2ibek does not convert ADPandABlocks
entities into the ioc.yaml. Instead it splits them out before dispatch:

- **Dedicated IOC**: the XML holds only PandAs, the elements that belong to
  them and boilerplate (devIocStats, autosave, EpicsEnvSet, pvlogging). The
  whole service becomes one fastcs-pandablocks instance under the IOC's own
  service name, with one controller per PandA. No ioc.yaml is written.
- **Mixed IOC**: the XML also has other devices. The ioc.yaml keeps those, and
  each PandA gets its own fastcs-pandablocks instance, named from its PV
  prefix in lowercase, as a sibling service folder.

The elements that belong to a PandA are the ADPandABlocks elements themselves
(ADPandABlocks, MotorSync), the areaDetector plugins whose data comes from a
PandA's port (followed down the NDARRAY_PORT chain), and the dbpf,
StartupCommand and pvlogging.BlacklistPv elements that act on PVs under a
PandA's prefix (they tune those plugins). fastcs-pandablocks does its own data
capture, so none of them has a counterpart.
"""

from __future__ import annotations

import difflib
import io
import ipaddress
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from builder2ibek.builder import Builder
from builder2ibek.types import Element, Entity, Generic_IOC

#: The fastcs-pandablocks image every generated instance runs. Bump the tag
#: here, and vendor the matching schema into tests/samples/fastcs-pandablocks/.
FASTCS_PANDABLOCKS_IMAGE = "ghcr.io/pandablocks/fastcs-pandablocks:0.2.2"

#: The ``type:`` discriminator of a fastcs-pandablocks controller entry
CONTROLLER_TYPE = "fastcs_pandablocks.PandaController"

#: Scaffold folder for a fastcs instance, relative to ``services/``
FASTCS_IOC_TEMPLATE = ".fastcs_ioc_template"

#: The config file the instance's args point fastcs-pandablocks at
CONTROLLER_YAML = "controller.yaml"

ADPANDABLOCKS = "ADPandABlocks"

# XML element types that are boilerplate in a PandA IOC: they say nothing about
# devices, so an IOC holding only these besides its PandAs is dedicated
_BOILERPLATE_MODULES = {"devIocStats", "autosave"}
_BOILERPLATE_TYPES = {"EPICS_BASE.EpicsEnvSet", "pvlogging.PvLogging"}

# XML element types that tune PVs; they belong to a PandA when they name a PV
# under its prefix
_PV_SETTING_TYPES = {
    "EPICS_BASE.dbpf",
    "EPICS_BASE.StartupCommand",
    "pvlogging.BlacklistPv",
}

_DEV_C7_RE = re.compile(r"^dev-c7:", re.MULTILINE)

# BL<nn><letter>- IOC prefixes map to beamline names (services-repo-resolution)
_BEAMLINE_RE = re.compile(r"^BL(\d{2})([IJKBC])-")
_BEAMLINE_LETTERS = {"I": "i{}", "J": "i{}-1", "K": "i{}-2", "B": "b{}", "C": "b{}-1"}


@dataclass
class PandA:
    """One ADPandABlocks.ADPandABlocks element"""

    prefix: str  # P: the PV prefix the PandA's PVs were rooted at
    address: str  # HOST: hostname or IP address of the box
    port: str  # PORT: the asyn port, which plugins and MotorSync refer to

    @property
    def instance(self) -> str:
        """The service name of this PandA's own fastcs instance"""
        return self.prefix.lower()


@dataclass
class PandaSplit:
    """The PandAs of an IOC and what was split out of its XML with them"""

    pandas: list[PandA]
    dedicated: bool
    # the XML elements split out with the PandAs
    dropped: list[Element] = field(default_factory=list)


def _type(element: Element) -> str:
    return f"{element.module}.{element.name}"


def _names_panda_pv(element: Element, prefixes: list[str]) -> bool:
    return any(
        f"{prefix}:" in value
        for value in element.attributes.values()
        for prefix in prefixes
    )


def _owned(elements: list[Element], pandas: list[PandA]) -> list[bool]:
    """Which elements belong to a PandA"""
    prefixes = [p.prefix for p in pandas]
    ports = {p.port for p in pandas}
    owned = [e.module == ADPANDABLOCKS for e in elements]

    # follow the areaDetector plugin chain down from each PandA port
    changed = True
    while changed:
        changed = False
        for i, element in enumerate(elements):
            if owned[i]:
                continue
            if element.attributes.get("NDARRAY_PORT") in ports:
                owned[i] = changed = True
                if port := element.attributes.get("PORT"):
                    ports.add(port)

    for i, element in enumerate(elements):
        if _type(element) in _PV_SETTING_TYPES and _names_panda_pv(element, prefixes):
            owned[i] = True
    return owned


def _is_boilerplate(element: Element) -> bool:
    return element.module in _BOILERPLATE_MODULES or _type(element) in (
        _BOILERPLATE_TYPES
    )


def split_pandas(builder: Builder, ioc: Generic_IOC) -> PandaSplit | None:
    """
    Take the PandAs, and the elements that belong to them, out of builder's
    elements before dispatch. Returns None when the IOC has no PandA.

    For a mixed IOC, any remaining element that still names a PandA PV gets a
    warning: fastcs-pandablocks PV names differ. The dropped elements are
    recorded as won't convert by record_wont_convert, once the instances have
    been written.
    """
    pandas = [
        PandA(
            prefix=e.attributes["P"],
            address=e.attributes["HOST"],
            port=e.attributes["PORT"],
        )
        for e in builder.elements
        if _type(e) == f"{ADPANDABLOCKS}.{ADPANDABLOCKS}"
    ]
    if not pandas:
        return None

    owned = _owned(builder.elements, pandas)
    kept = [e for e, o in zip(builder.elements, owned, strict=True) if not o]
    dropped = [e for e, o in zip(builder.elements, owned, strict=True) if o]
    split = PandaSplit(
        pandas=pandas,
        dedicated=all(_is_boilerplate(e) for e in kept),
        dropped=dropped,
    )
    builder.elements = kept
    if split.dedicated:
        return split

    prefixes = [p.prefix for p in pandas]
    for element in kept:
        for key, value in element.attributes.items():
            if any(f"{prefix}:" in value for prefix in prefixes):
                ioc.extra_warnings.append(
                    f"{Path(ioc.source_file).stem}: {_type(element)} {key} names "
                    f"the PandA PV {value}: fastcs-pandablocks PV names differ, "
                    "update it by hand"
                )
    return split


def _note(element: Element) -> str:
    if element.name == "MotorSync":
        return (
            f"MotorSync of {element.attributes.get('MOTOR', '?')} (encoder "
            f"{element.attributes.get('ENC_IND', '?')}): fastcs-pandablocks has "
            "no equivalent"
        )
    return ""


def record_wont_convert(ioc: Generic_IOC, split: PandaSplit, outcome: str) -> None:
    """Record a mixed IOC's dropped elements as won't convert"""
    reason = f"ADPandABlocks is replaced by fastcs-pandablocks: {outcome}"
    for element in split.dropped:
        entity = Entity(element.attributes)
        entity.type = _type(element)
        ioc.wont_convert(entity, reason, note=_note(element))


PV_NAMES_DIFFER = (
    "fastcs-pandablocks serves PVA only, and its PV names below the prefix "
    "differ from ADPandABlocks': update GDA, ophyd-async and screens"
)


def _counts(elements: list[Element]) -> str:
    return ", ".join(f"{n} {t}" for t, n in Counter(map(_type, elements)).items())


def dedicated_warnings(ioc_name: str, split: PandaSplit) -> list[str]:
    """What a dedicated IOC loses on becoming a fastcs instance"""
    motor_syncs = [e for e in split.dropped if _type(e) == "ADPandABlocks.MotorSync"]
    settings = [e for e in split.dropped if _type(e) in _PV_SETTING_TYPES]
    plugins = [
        e
        for e in split.dropped
        if e.module != ADPANDABLOCKS and _type(e) not in _PV_SETTING_TYPES
    ]
    warnings = []
    if motor_syncs:
        warnings.append(
            f"{ioc_name}: won't convert {_counts(motor_syncs)}: "
            "fastcs-pandablocks has no equivalent"
        )
    if plugins:
        warnings.append(
            f"{ioc_name}: won't convert {_counts(plugins)}: areaDetector plugins "
            "fed by the PandA; fastcs-pandablocks does its own data capture"
        )
    if settings:
        warnings.append(
            f"{ioc_name}: won't convert {_counts(settings)}: they act on PVs of "
            "the PandA's ADPandABlocks driver and plugins, which "
            "fastcs-pandablocks does not have"
        )
    return warnings


# Writing fastcs instances ####################################################


def beamline_data_dir(prefix: str) -> str | None:
    """
    The beamline data folder for a PV or IOC prefix, e.g. BL08J-... ->
    /dls/i08-1/data; None when the prefix names no known beamline.
    """
    m = _BEAMLINE_RE.match(prefix.upper())
    if not m:
        return None
    return f"/dls/{_BEAMLINE_LETTERS[m.group(2)].format(m.group(1))}/data"


def _q(value: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)"""
    return json.dumps(value)


def controller_yaml(pandas: list[PandA], title: str) -> str:
    """config/controller.yaml: one controller per PandA, served over PVA"""
    version = FASTCS_PANDABLOCKS_IMAGE.rsplit(":", 1)[1]
    schema = (
        "https://raw.githubusercontent.com/PandABlocks/fastcs-PandABlocks/"
        f"{version}/src/fastcs_pandablocks/panda/schema.json"
    )
    controllers = "".join(
        f"  - id: {_q(p.prefix)}\n"
        f"    type: {_q(CONTROLLER_TYPE)}\n"
        f"    address: {_q(p.address)}\n"
        for p in pandas
    )
    return f"""\
# yaml-language-server: $schema={schema}

# each controller's id is the PV prefix its PVs are served under
controllers:
{controllers}
transport:
  - epicspva: {{}}
    gui:
      title: {_q(title)}
      output_dir: "/epics/opi"
"""


def _indented_yaml(data: dict, indent: str) -> str:
    stream = io.StringIO()
    dumper = YAML()
    dumper.default_flow_style = False
    dumper.dump(data, stream)
    return "".join(f"{indent}{line}" for line in stream.getvalue().splitlines(True))


def values_yaml(data_dir: str, security_context: dict | None = None) -> str:
    """
    values.yaml for a fastcs-pandablocks instance. security_context is one
    carried over from the ibek values.yaml the instance replaces.
    """
    run = f"fastcs-pandablocks run /epics/ioc/config/{CONTROLLER_YAML}"
    args = f"stdio-expose --ptty --stdin --ctrl-d '{run}'"
    if security_context:
        security = "\n  # carried over from the ibek values.yaml\n" + _indented_yaml(
            {"securityContext": security_context}, "  "
        )
    else:
        security = ""
    return f"""\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: {_q(FASTCS_PANDABLOCKS_IMAGE)}
  args:
    - {_q(args)}
{security}
  # fastcs-pandablocks writes its captured data here; writing as the beamline
  # user needs a securityContext with that user's runAsUser and runAsGroup
  dataVolume:
    pvc: false
    hostPath: {_q(data_dir)}

  # DO NOT use the default livenessProbe and preStop from ioc-instance.
  # Leave blank or provide a path to an executable inside the container image.
  livenessExecutable: ""
  preStopExecutable: ""

  resources:
    limits:
      cpu: 1000m
      memory: 4Gi
    requests:
      cpu: 1000m
      memory: 4Gi
"""


def _is_legacy(folder: Path) -> bool:
    values = folder / "values.yaml"
    return values.is_file() and bool(_DEV_C7_RE.search(values.read_text()))


def _is_empty(folder: Path) -> bool:
    """True when folder holds no files, only (possibly) empty folders"""
    return all(p.is_dir() and not p.is_symlink() for p in folder.rglob("*"))


def _copy_scaffold(template: Path, target: Path) -> list[Path]:
    """
    Copy template into target, reproducing its symlinks (Chart.yaml and
    templates link into ../../.helm-shared) and keeping files target has.
    A real file or folder where the template has a symlink is kept, never
    deleted: those paths are returned so the caller can warn about them.
    """
    kept: list[Path] = []
    target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(template.iterdir()):
        dest = target / entry.name
        if entry.is_symlink():
            link = os.readlink(entry)
            if dest.is_symlink():
                if os.readlink(dest) == link:
                    continue
                dest.unlink()  # a wrong link, not content
            elif dest.exists():
                kept.append(dest)
                continue
            os.symlink(link, dest)
        elif entry.is_dir():
            kept += _copy_scaffold(entry, dest)
        elif not dest.exists() and not dest.is_symlink():
            shutil.copyfile(entry, dest)
    return kept


# Reading the controllers other instances already serve ######################


@dataclass(frozen=True)
class Served:
    """A PandA controller some instance's controller.yaml already serves"""

    folder: Path
    prefix: str
    address: str


def read_controllers(controller: Path) -> list[tuple[str, str]]:
    """
    (prefix, address) of each PandA in a controller.yaml, in the 0.2.x shape
    (controllers[].id / address) or the 0.1.0 one (controller.address and a
    transport's pv_prefix). Unreadable files give an empty list.
    """
    try:
        doc = YAML(typ="safe").load(controller.read_text())
    except (YAMLError, OSError, UnicodeDecodeError):
        return []
    if not isinstance(doc, dict):
        return []
    found = []
    if isinstance(doc.get("controllers"), list):
        for entry in doc["controllers"]:
            if isinstance(entry, dict) and "address" in entry:
                found.append((str(entry.get("id", "")), str(entry["address"])))
    single = doc.get("controller")
    if isinstance(single, dict) and "address" in single:
        prefix = ""
        for transport in doc.get("transport") or []:
            for options in (transport or {}).values():
                if isinstance(options, dict) and options.get("pv_prefix"):
                    prefix = str(options["pv_prefix"])
        found.append((prefix, str(single["address"])))
    return found


def served_controllers(services: Path) -> list[Served]:
    """Every PandA controller served by an instance folder in services"""
    if not services.is_dir():
        return []
    served = []
    for controller in sorted(services.glob(f"*/config/{CONTROLLER_YAML}")):
        folder = controller.parent.parent
        if folder.name.startswith("."):
            continue  # .fastcs_ioc_template and friends
        served += [Served(folder, p, a) for p, a in read_controllers(controller)]
    return served


def short_address(address: str) -> str:
    """
    An address to compare boxes by: an IP address as given, a hostname
    lowercased without its domain (panda-01.diamond.ac.uk -> panda-01)
    """
    try:
        return str(ipaddress.ip_address(address.strip()))
    except ValueError:
        return address.strip().lower().split(".")[0]


def _duplicate(panda: PandA, served: list[Served], target: Path) -> Served | None:
    for s in served:
        if s.folder == target:
            continue
        if s.prefix == panda.prefix or short_address(s.address) == short_address(
            panda.address
        ):
            return s
    return None


# Planning, then writing #####################################################


@dataclass
class Target:
    """One fastcs instance folder to write"""

    folder: Path
    pandas: list[PandA]
    title: str
    # new: write it; rerun: an instance this tool wrote for the same PandAs,
    # left alone; diverged: this IOC's fastcs-pandablocks instance with
    # different (hand-edited) controllers, left alone for a manual merge;
    # legacy: a dev-c7 folder, recreated; ibek: the IOC's own ibek folder,
    # which becomes the fastcs instance
    state: str


def _ibek_stale_files(folder: Path, ioc_name: str) -> list[Path]:
    """
    The files builder2ibek's ibek flow puts in an instance folder, which a
    fastcs instance does not use: the ioc.yaml and its schema, the pvlogging
    blacklist, and runtime-lock.yaml with the pattern files it vendored.
    """
    config = folder / "config"
    names = ["ioc.yaml", "ioc.schema.json", f"{ioc_name.lower()}_blacklist.txt"]
    names.append("pvlogging_excl.txt")
    # the schema sits at the folder root in services repos, config/ in some
    stale = [config / n for n in names] + [folder / "ioc.schema.json"]
    lock = folder / "runtime-lock.yaml"
    if lock.is_file():
        stale.append(lock)
        try:
            doc = YAML(typ="safe").load(lock.read_text()) or {}
        except (YAMLError, OSError, UnicodeDecodeError):
            doc = {}
        for pattern in (doc.get("patterns") or {}).values():
            for path in (pattern or {}).get("files") or {}:
                if str(path).startswith("config/") and "/.." not in str(path):
                    stale.append(folder / str(path))
    return [p for p in stale if p.is_file() or p.is_symlink()]


def _classify(folder: Path, pandas: list[PandA], ibek_ok: bool) -> str | None:
    """The Target state for folder, or None when it belongs to something else"""
    if not folder.exists() or _is_empty(folder):
        return "new"
    if _is_legacy(folder):
        return "legacy"
    controller = folder / "config" / CONTROLLER_YAML
    if controller.is_file():
        wanted = sorted((p.prefix, p.address.lower()) for p in pandas)
        held = sorted((p, a.lower()) for p, a in read_controllers(controller))
        if held == wanted:
            return "rerun"
        # the folder is this IOC's (or this PandA's) by name; a
        # fastcs-pandablocks values.yaml says builder2ibek wrote it
        values = folder / "values.yaml"
        image = FASTCS_PANDABLOCKS_IMAGE.split(":")[0]
        if values.is_file() and image in values.read_text():
            return "diverged"
        return None
    if ibek_ok and (folder / "config" / "ioc.yaml").is_file():
        return "ibek"
    return None


@dataclass
class FastcsPlan:
    """What write_fastcs will do, decided before anything is written"""

    targets: list[Target]
    # PandAs refused because another instance already serves them
    refused: list[tuple[PandA, Served]]
    # the ioc.yaml path is a services-repo instance folder's own ioc.yaml
    in_services: bool


def is_services_ioc_yaml(yaml: Path) -> bool:
    """True for services/<name>/config/ioc.yaml"""
    yaml = yaml.absolute()
    return (
        yaml.name == "ioc.yaml"
        and yaml.parent.name == "config"
        and yaml.parent.parent.parent.name == "services"
    )


def plan_fastcs(ioc_name: str, split: PandaSplit, yaml: Path) -> FastcsPlan:
    """
    Decide every instance folder before writing any. In a services repo the
    IOC's own folder is services/<ioc>/ and siblings go in services/; anywhere
    else every instance is a folder next to the ioc.yaml.

    A PandA that another instance already serves (same prefix or address) is
    refused. A target folder that holds anything other than a fresh, legacy or
    re-run instance (or, for a dedicated IOC, its own ibek folder) raises
    FileExistsError, so nothing is written.
    """
    in_services = is_services_ioc_yaml(yaml)
    parent = yaml.absolute().parent
    own = parent.parent if in_services else parent / ioc_name.lower()
    siblings = own.parent if in_services else parent
    served = served_controllers(siblings)

    if split.dedicated:
        groups = [(own, split.pandas, ioc_name)]
    else:
        # a PandA named like the IOC itself gets <prefix>-panda, so its
        # instance never lands in the IOC's own folder
        groups = [
            (
                siblings / p.instance
                if siblings / p.instance != own
                else siblings / f"{p.instance}-panda",
                [p],
                p.prefix,
            )
            for p in split.pandas
        ]

    targets, refused, conflicts = [], [], []
    for folder, pandas, title in groups:
        dupes = [(p, d) for p in pandas if (d := _duplicate(p, served, folder))]
        if dupes:
            # a dedicated IOC's instance is written whole or not at all
            refused += dupes
            continue
        state = _classify(folder, pandas, ibek_ok=split.dedicated and in_services)
        if state is None:
            conflicts.append(folder)
        else:
            targets.append(Target(folder, pandas, title, state))

    if conflicts:
        raise FileExistsError(
            f"{ioc_name}: not writing fastcs-pandablocks instances, these folders "
            "already hold something else: " + ", ".join(map(str, conflicts))
        )
    return FastcsPlan(targets, refused, in_services)


def _write_target(target: Target, ioc_name: str) -> tuple[list[str], list[str]]:
    """Write one planned instance. Returns (notes, warnings)."""
    folder = target.folder
    generated = controller_yaml(target.pandas, target.title)
    controller = folder / "config" / CONTROLLER_YAML

    if target.state in ("rerun", "diverged"):
        existing = controller.read_text()
        if existing == generated:
            return [], []
        diff = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                str(controller),
                "generated",
            )
        )
        if target.state == "diverged":
            what = (
                "serves different controllers from the ones the XML gives; it was "
                "left alone, merge by hand"
            )
        else:
            what = "differs from what builder2ibek generates and was left alone"
        return [f"{ioc_name}: {controller} {what}:\n{diff}"], []

    notes: list[str] = []
    warnings: list[str] = []
    security_context = None
    data_dir = beamline_data_dir(target.pandas[0].prefix)
    if target.state == "legacy":
        shutil.rmtree(folder)
    elif target.state == "ibek":
        security_context, hostpath, values_note = _carry_over_values(folder, ioc_name)
        data_dir = hostpath or data_dir
        notes.append(values_note)
        removed = _ibek_stale_files(folder, ioc_name)
        for path in removed:
            path.unlink()
        names = ", ".join(str(p.relative_to(folder)) for p in removed)
        left = sorted(
            p.name for p in (folder / "config").iterdir() if p.name != CONTROLLER_YAML
        )
        notes.append(
            f"{ioc_name}: removed the ibek files {names} from {folder}"
            + (f"; left in config/: {', '.join(left)}" if left else "")
        )

    if data_dir is None:
        data_dir = "REPLACE_WITH_DATA_PATH"
        warnings.append(
            f"{ioc_name}: no beamline data folder known for "
            f"{target.pandas[0].prefix}, set dataVolume.hostPath in "
            f"{folder / 'values.yaml'}"
        )
    (folder / "config").mkdir(parents=True, exist_ok=True)
    (folder / "values.yaml").write_text(values_yaml(data_dir, security_context))
    controller.write_text(generated)
    template = folder.parent / FASTCS_IOC_TEMPLATE
    if template.is_dir():
        # after writing ours, so only the scaffold's links and extras are added
        for path in _copy_scaffold(template, folder):
            kind = "folder" if path.is_dir() else "file"
            warnings.append(
                f"{ioc_name}: kept {path}, a real {kind} "
                f"where {template.name} has a symlink; replace it with the link "
                "by hand if it holds nothing of yours"
            )
    return notes, warnings


# ioc-instance keys of an ibek values.yaml that a fastcs instance replaces on
# purpose, or carries over (securityContext, dataVolume.hostPath)
_IBEK_VALUES_HANDLED = {"image", "startupExecutable", "securityContext", "dataVolume"}


def _carry_over_values(
    folder: Path, ioc_name: str
) -> tuple[dict | None, str | None, str]:
    """
    What a dedicated IOC's ibek values.yaml passes to its fastcs one: a
    securityContext and dataVolume.hostPath. When it holds anything else, it
    is kept as values.yaml.ibek. Returns (securityContext, hostPath, note).
    """
    values = folder / "values.yaml"
    if not values.is_file():
        return None, None, f"{ioc_name}: {folder} had no values.yaml"
    try:
        doc = YAML(typ="safe").load(values.read_text()) or {}
    except (YAMLError, UnicodeDecodeError):
        doc = None
    instance = doc.get("ioc-instance") if isinstance(doc, dict) else None
    if not isinstance(instance, dict):
        instance = {}
    security = instance.get("securityContext")
    security = security if isinstance(security, dict) and security else None
    volume = instance.get("dataVolume")
    volume = volume if isinstance(volume, dict) else {}
    hostpath = volume.get("hostPath")
    hostpath = str(hostpath) if hostpath else None

    carried = []
    if security:
        carried.append("securityContext")
    if hostpath:
        carried.append("dataVolume.hostPath")
    others = [] if isinstance(doc, dict) else ["(unreadable)"]
    if isinstance(doc, dict):
        others += [k for k in doc if k != "ioc-instance"]
        others += [k for k in instance if k not in _IBEK_VALUES_HANDLED]
        others += [f"dataVolume.{k}" for k in volume if k not in ("hostPath", "pvc")]

    note = f"{ioc_name}: replaced the ibek {values}"
    note += f", carrying over {' and '.join(carried)}" if carried else ""
    if others:
        backup = folder / "values.yaml.ibek"
        shutil.copyfile(values, backup)
        note += f"; kept it as {backup}, it also set {', '.join(others)}"
    return security, hostpath, note


@dataclass
class FastcsResult:
    """What write_fastcs did"""

    # instance folders written, or re-run and left alone
    folders: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # PandAs not written because another instance already serves them
    refused: list[PandA] = field(default_factory=list)

    def outcome(self) -> str:
        """The won't-convert reason for a mixed IOC's dropped elements"""
        parts = []
        if self.folders:
            names = ", ".join(f.name for f in self.folders)
            parts.append(f"written as the fastcs instance(s) {names}")
        if self.refused:
            names = ", ".join(p.prefix for p in self.refused)
            parts.append(f"not written for {names}, already served elsewhere")
        return "; ".join(parts)


def write_fastcs(ioc_name: str, split: PandaSplit, yaml: Path) -> FastcsResult:
    """
    Write the fastcs instances for split next to the ioc.yaml path given.
    ioc_name is the XML file's stem, e.g. BL08J-MO-IOC-11. Every folder is
    checked (plan_fastcs) before any is written.
    """
    plan = plan_fastcs(ioc_name, split, yaml)
    result = FastcsResult(refused=[p for p, _ in plan.refused])
    result.warnings = [
        f"{ioc_name}: refused to write a fastcs-pandablocks instance for "
        f"{panda.prefix} ({panda.address}): {served.folder} already serves "
        f"{served.prefix or '?'} at {served.address}"
        for panda, served in plan.refused
    ]
    if split.dedicated and plan.refused:
        # a dedicated IOC's instance is written whole or not at all
        result.refused = list(split.pandas)
        result.warnings.append(
            f"{ioc_name}: nothing was written for any of this dedicated IOC's "
            f"{len(split.pandas)} PandA(s): "
            + ", ".join(p.prefix for p in split.pandas)
        )

    for target in plan.targets:
        target_notes, target_warnings = _write_target(target, ioc_name)
        result.folders.append(target.folder)
        result.warnings += target_warnings
        what = "kept" if target.state in ("rerun", "diverged") else "wrote"
        prefixes = ", ".join(p.prefix for p in target.pandas)
        result.notes.append(
            f"{ioc_name}: {what} the fastcs-pandablocks instance {target.folder} "
            f"for {prefixes}. {PV_NAMES_DIFFER}"
        )
        result.notes += target_notes

    if split.dedicated and result.folders:
        result.warnings += dedicated_warnings(ioc_name, split)
        if plan.in_services:
            result.notes.append(f"{ioc_name}: dedicated PandA IOC, no ioc.yaml written")
        else:
            result.notes.append(
                f"{ioc_name}: dedicated PandA IOC, no ioc.yaml written; {yaml} is "
                "outside a services repo instance folder, so it was left alone"
            )
    return result
