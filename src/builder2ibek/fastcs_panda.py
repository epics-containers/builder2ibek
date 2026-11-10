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

import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

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
    # the fastcs instance names the PandAs go to
    instances: list[str]
    # XML type -> count of the elements split out with the PandAs
    dropped: Counter[str] = field(default_factory=Counter)


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

    For a mixed IOC each element taken out is recorded as won't convert,
    naming the fastcs instances written, and any remaining element that still
    names a PandA PV gets a warning: fastcs-pandablocks PV names differ.
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
    dedicated = all(_is_boilerplate(e) for e in kept)

    ioc_name = Path(ioc.source_file).stem.lower()
    instances = [ioc_name] if dedicated else [p.instance for p in pandas]
    split = PandaSplit(
        pandas=pandas,
        dedicated=dedicated,
        instances=instances,
        dropped=Counter(_type(e) for e in dropped),
    )

    builder.elements = kept
    if dedicated:
        return split

    reason = (
        "ADPandABlocks is replaced by fastcs-pandablocks, written as the "
        f"fastcs instance(s) {', '.join(instances)}"
    )
    for element in dropped:
        entity = Entity(element.attributes)
        entity.type = _type(element)
        ioc.wont_convert(entity, reason, note=_note(element))

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


PV_NAMES_DIFFER = (
    "fastcs-pandablocks serves PVA only, and its PV names below the prefix "
    "differ from ADPandABlocks': update GDA, ophyd-async and screens"
)


def dedicated_warnings(ioc_name: str, split: PandaSplit) -> list[str]:
    """What a dedicated IOC loses on becoming a fastcs instance"""
    warnings = []
    motor_syncs = split.dropped.get(f"{ADPANDABLOCKS}.MotorSync", 0)
    if motor_syncs:
        warnings.append(
            f"{ioc_name}: won't convert {motor_syncs} ADPandABlocks.MotorSync: "
            "fastcs-pandablocks has no equivalent"
        )
    plugins = ", ".join(
        f"{n} {t}" for t, n in split.dropped.items() if not t.startswith(ADPANDABLOCKS)
    )
    if plugins:
        warnings.append(
            f"{ioc_name}: won't convert {plugins}: fastcs-pandablocks does its "
            "own data capture"
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


def controller_yaml(pandas: list[PandA], title: str) -> str:
    """config/controller.yaml: one controller per PandA, served over PVA"""
    version = FASTCS_PANDABLOCKS_IMAGE.rsplit(":", 1)[1]
    schema = (
        "https://raw.githubusercontent.com/PandABlocks/fastcs-PandABlocks/"
        f"{version}/src/fastcs_pandablocks/panda/schema.json"
    )
    controllers = "".join(
        f"  - id: {p.prefix}\n    type: {CONTROLLER_TYPE}\n    address: {p.address}\n"
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
      title: {title}
      output_dir: /epics/opi
"""


def values_yaml(data_dir: str) -> str:
    """values.yaml for a fastcs-pandablocks instance"""
    run = f"fastcs-pandablocks run /epics/ioc/config/{CONTROLLER_YAML}"
    return f"""\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: {FASTCS_PANDABLOCKS_IMAGE}
  args:
    - stdio-expose --ptty --stdin --ctrl-d '{run}'

  # fastcs-pandablocks writes its captured data here; writing as the beamline
  # user needs a securityContext with that user's runAsUser and runAsGroup
  dataVolume:
    pvc: false
    hostPath: {data_dir}

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


def _copy_scaffold(template: Path, target: Path) -> None:
    """
    Copy template into target, reproducing its symlinks (Chart.yaml and
    templates link into ../../.helm-shared) and keeping files target has
    """
    target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(template.iterdir()):
        dest = target / entry.name
        if entry.is_symlink():
            link = os.readlink(entry)
            if dest.is_symlink() and os.readlink(dest) == link:
                continue
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            os.symlink(link, dest)
        elif entry.is_dir():
            _copy_scaffold(entry, dest)
        elif not dest.exists() and not dest.is_symlink():
            shutil.copyfile(entry, dest)


def write_instance(
    folder: Path, pandas: list[PandA], title: str, own_ioc_yaml: Path | None = None
) -> list[str]:
    """
    Write a fastcs-pandablocks instance into folder, scaffolded from the
    sibling .fastcs_ioc_template when there is one.

    own_ioc_yaml is the ioc.yaml this conversion would otherwise have written
    (a dedicated IOC's own folder): it is removed. Any other folder that holds
    an ibek ioc.yaml belongs to a different IOC and is refused, unless it is a
    legacy dev-c7 folder, which is recreated.

    Returns warnings for things a human must still fill in.
    """
    warnings = []
    ioc_yaml = folder / "config" / "ioc.yaml"
    if _is_legacy(folder):
        shutil.rmtree(folder)
    elif ioc_yaml.exists() and ioc_yaml != own_ioc_yaml:
        raise FileExistsError(
            f"{folder} holds an ibek ioc.yaml, not writing a fastcs-pandablocks "
            "instance over it"
        )

    template = folder.parent / FASTCS_IOC_TEMPLATE
    if template.is_dir():
        _copy_scaffold(template, folder)
    (folder / "config").mkdir(parents=True, exist_ok=True)
    if own_ioc_yaml is not None:
        own_ioc_yaml.unlink(missing_ok=True)

    data_dir = beamline_data_dir(pandas[0].prefix)
    if data_dir is None:
        data_dir = "REPLACE_WITH_DATA_PATH"
        warnings.append(
            f"{folder.name}: no beamline data folder known for {pandas[0].prefix}, "
            f"set dataVolume.hostPath in {folder / 'values.yaml'}"
        )
    (folder / "values.yaml").write_text(values_yaml(data_dir))
    (folder / "config" / CONTROLLER_YAML).write_text(controller_yaml(pandas, title))
    return warnings


def instance_dirs(yaml: Path, ioc_name: str) -> tuple[Path, Path]:
    """
    (the IOC's own instance folder, the folder sibling instances go in) for the
    ioc.yaml path xml2yaml was given. In a services repo the path is
    services/<ioc>/config/ioc.yaml, so siblings go in services/. Anywhere else
    every instance, the IOC's own included, is a folder next to the ioc.yaml.
    """
    parent = yaml.parent.absolute()
    if parent.name == "config":
        return parent.parent, parent.parent.parent
    return parent / ioc_name, parent


def write_fastcs(
    ioc_name: str, split: PandaSplit, yaml: Path
) -> tuple[list[Path], list[str], list[str]]:
    """
    Write the fastcs instances for split next to the ioc.yaml path given.
    ioc_name is the XML file's stem, e.g. BL08J-MO-IOC-11.
    Returns the instance folders written, notes saying so, and warnings.
    """
    instance, siblings = instance_dirs(yaml, ioc_name.lower())
    if split.dedicated:
        warnings = write_instance(
            instance, split.pandas, ioc_name, own_ioc_yaml=yaml.absolute()
        )
        notes = [
            f"{ioc_name}: dedicated PandA IOC, wrote the fastcs-pandablocks "
            f"instance {instance} for {len(split.pandas)} PandA(s) instead of an "
            f"ioc.yaml. {PV_NAMES_DIFFER}"
        ]
        return [instance], notes, dedicated_warnings(ioc_name, split) + warnings

    folders, notes, warnings = [], [], []
    for panda in split.pandas:
        folder = siblings / panda.instance
        warnings += write_instance(folder, [panda], panda.prefix)
        folders.append(folder)
        notes.append(
            f"{ioc_name}: wrote the fastcs-pandablocks instance {folder} for the "
            f"PandA {panda.prefix}. {PV_NAMES_DIFFER}"
        )
    return folders, notes, warnings
