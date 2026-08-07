"""Writing a converted beamline back into an epics-containers services repo.

A services repo looks like this (paths relative to the repo root)::

    .helm-shared/Chart.yaml
    .helm-shared/LegacyChart.yaml
    .helm-shared/values.schema.json
    .helm-shared/templates/ioc_instance.yaml
    services/.ioc_template/          scaffold for an ibek IOC
    services/.fastcs_ioc_template/   scaffold for a FastCS IOC
    services/<instance>/             one folder per deployed IOC

Every IOC folder -- template or real -- carries ``Chart.yaml`` and ``templates``
as **relative symlinks** into ``../../.helm-shared/``, never as copies. Git
tracks ``services/<instance>/templates`` as a single mode-120000 entry, so a
generator that copied the directory would produce a diff nobody wants. All the
scaffolding here goes through :func:`_link_like`, which reads the link target
off the template with :func:`os.readlink` and reproduces it verbatim.

Three functions do the work:

* :func:`scaffold` materialises (or repairs) one IOC folder from a template.
* :func:`write_catio_ioc` fills a scaffold in with the generated fastcs-catio
  IOC for one :class:`~builder2ibek.catio.chains.Chain`.
* :func:`write_ioc` fills a scaffold in with a converted ibek IOC.

:func:`read_sticky_ordinals` closes the loop: it reads the ``E{n}RIO`` ordinal
back out of every ``config/fastcs.yaml`` a previous run wrote, so re-running the
conversion never renumbers a chain. Renumbering would repoint every rewritten PV
at nothing.

This module never imports ``fastcs_catio``, and imports the rest of
``builder2ibek`` lazily, so it stays cheap under ``--doctest-modules``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from builder2ibek.catio.chains import Chain
    from builder2ibek.types import Generic_IOC

__all__ = [
    "CATIO_CONTROLLER_TYPE",
    "CATIO_IMAGE",
    "FASTCS_IOC_TEMPLATE",
    "IBEK_PLACEHOLDERS",
    "IOC_SCHEMA",
    "IOC_TEMPLATE",
    "PLACEHOLDER_RE",
    "is_legacy",
    "read_sticky_ordinals",
    "scaffold",
    "write_catio_ioc",
    "write_ioc",
]

#: The ``type:`` discriminator of a fastcs-catio controller entry. Verified
#: against ``fastcs_catio/schema.json`` (``CATioServerControllerEntry.type`` is
#: a ``const``).
CATIO_CONTROLLER_TYPE = "fastcs_catio.CATioServerController"

#: The container image holding fastcs-catio. The tag is deliberately left as a
#: placeholder -- pinning it is a human decision, not a conversion output.
CATIO_IMAGE = "ghcr.io/diamondlightsource/fastcs-catio"

#: The fastcs-catio console script, from its ``[project.scripts]``.
CATIO_ENTRYPOINT = "fastcs-catio"

#: Scaffold folder for an ibek IOC, relative to ``services/``.
IOC_TEMPLATE = ".ioc_template"

#: Scaffold folder for a FastCS IOC, relative to ``services/``.
FASTCS_IOC_TEMPLATE = ".fastcs_ioc_template"

#: ``$schema`` written into a converted ``config/ioc.yaml``. Matches
#: ``.ioc_template/config/ioc.yaml`` and every real IOC in i21-services.
IOC_SCHEMA = "../ioc.schema.json"

#: The FastCS config filename. fastcs-catio's own reference config is called
#: ``fastcs.yaml`` and so are 4 of the 6 deployed FastCS IOCs; the i21 scaffold
#: ships a ``controller.yaml`` example that :func:`write_catio_ioc` removes.
FASTCS_CONFIG = "fastcs.yaml"

#: The example config shipped in ``.fastcs_ioc_template/config/``.
FASTCS_EXAMPLE_CONFIG = "controller.yaml"

#: Anything a human still has to fill in.
PLACEHOLDER_RE = re.compile(r"REPLACE_WITH_[A-Z0-9_]+")

#: Placeholders :func:`write_ioc` leaves behind. It never touches ``values.yaml``,
#: so a freshly scaffolded ibek IOC keeps the template's image placeholder.
IBEK_PLACEHOLDERS = ("REPLACE_WITH_IMAGE_URI",)

#: Pulls the chain ordinal out of a ``node_prefix`` such as
#: ``"BL21I-VA-E1RIO-{:02d}"``.
_ORDINAL_RE = re.compile(r"E(\d+)RIO")

#: A top-level ``dev-c7:`` key -- column 0, so an indented ``dev-c7`` inside an
#: image tag does not match. See :func:`is_legacy`.
_DEV_C7_RE = re.compile(r"^dev-c7:", re.MULTILINE)

_LEGACY_CHART = "LegacyChart.yaml"


def _services(services_repo: Path) -> Path:
    """The ``services/`` directory of *services_repo*."""
    return Path(services_repo) / "services"


def is_legacy(folder: Path) -> bool:
    """Is *folder* a DLS legacy (``dev-c7``) IOC that must be recreated?

    Two independent signals, either of which is conclusive:

    1. ``Chart.yaml`` is a symlink to ``LegacyChart.yaml``.
    2. ``values.yaml`` has a ``dev-c7:`` key at **column 0**.

    The column-0 anchor matters. ``bl21i-ea-ioc-01-debug`` is a perfectly good
    ibek IOC whose ``values.yaml`` contains
    ``image: ghcr.io/diamondlightsource/dev-c7:2025.11.1-beta.1``; a substring
    match would delete it.

    A folder that does not exist is not legacy.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return False

    chart = folder / "Chart.yaml"
    if chart.is_symlink() and Path(os.readlink(chart)).name == _LEGACY_CHART:
        return True

    values = folder / "values.yaml"
    if values.is_file():
        return bool(_DEV_C7_RE.search(values.read_text()))
    return False


def _link_like(template_entry: Path, target_entry: Path) -> None:
    """Reproduce the symlink *template_entry* at *target_entry*.

    The link **text** is copied verbatim (``../../.helm-shared/Chart.yaml``), so
    the result is relative and survives moving the repo. An existing entry at
    *target_entry* is replaced only when it is wrong, and is unlinked rather
    than removed recursively -- a ``templates`` symlink must never be followed
    into ``.helm-shared``.
    """
    link = os.readlink(template_entry)
    if target_entry.is_symlink():
        if os.readlink(target_entry) == link:
            return
        target_entry.unlink()
    elif target_entry.exists():
        # a real file or directory squatting where a symlink belongs
        if target_entry.is_dir():
            shutil.rmtree(target_entry)
        else:
            target_entry.unlink()
    os.symlink(link, target_entry)


def _copy_missing(template_dir: Path, target_dir: Path) -> None:
    """Copy *template_dir* into *target_dir*, preserving symlinks.

    Existing regular files are **kept** -- a hand-edited ``values.yaml`` with a
    real image reference must survive a re-run. Symlinks are always repaired,
    because a wrong ``Chart.yaml`` is never a deliberate local edit.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    for entry in sorted(template_dir.iterdir()):
        target = target_dir / entry.name
        if entry.is_symlink():
            _link_like(entry, target)
        elif entry.is_dir():
            _copy_missing(entry, target)
        elif not target.exists():
            # exists() follows symlinks, so a broken link reads as absent and
            # copyfile would then write *through* it, landing the file wherever
            # the link points -- possibly outside the instance folder.
            if target.is_symlink():
                target.unlink()
            shutil.copyfile(entry, target)


def scaffold(services_repo: Path, folder: str, *, fastcs: bool, dry_run: bool) -> Path:
    """Materialise ``services/<folder>`` from the appropriate template.

    :param services_repo: the repo **root** (the folder holding ``services/``).
    :param folder: the instance folder name, e.g. ``"bl21i-va-catio-01"``.
    :param fastcs: scaffold from ``.fastcs_ioc_template`` rather than
        ``.ioc_template``.
    :param dry_run: check everything, write nothing.
    :returns: the instance folder, whether or not it was written.
    :raises FileNotFoundError: the repo has no ``services/`` directory, or no
        template of the requested kind.
    :raises ValueError: *folder* is not a plain instance folder name.

    An existing **legacy** folder is deleted whole and recreated (CLAUDE.md's
    services-repo rule); an existing non-legacy folder is repaired in place,
    keeping every real file it already has.
    """
    # The legacy rule deletes folders, and `.legacy_ioc_template` is itself a
    # `dev-c7:` folder -- so never let a dotted or nested name through.
    if not folder or folder.startswith(".") or "/" in folder or folder == "..":
        raise ValueError(f"not an IOC instance folder name: {folder!r}")

    services = _services(services_repo)
    if not services.is_dir():
        raise FileNotFoundError(f"no services directory in {services_repo}")

    name = FASTCS_IOC_TEMPLATE if fastcs else IOC_TEMPLATE
    template = services / name
    if not template.is_dir():
        raise FileNotFoundError(f"no {name} in {services}")

    target = services / folder
    if dry_run:
        return target

    if is_legacy(target):
        # rmtree unlinks symlinks rather than descending them, so the
        # `templates` link is removed without touching .helm-shared/templates.
        shutil.rmtree(target)

    _copy_missing(template, target)
    return target


def _fastcs_yaml(chain: Chain) -> str:
    """The ``config/fastcs.yaml`` text for *chain*.

    The three ``name_mappings`` come straight from
    :meth:`~builder2ibek.catio.chains.Chain.name_mappings`, which is also what
    predicted the new PV names. That single source is the whole point: if the
    templates written here ever diverged from the ones used for prediction,
    every rewritten reference would point at a PV that does not exist.
    """
    mappings = chain.name_mappings()
    title = f"{chain.domain.replace('-', ' ')} EtherCAT chain"
    return f"""\
# Generated by `builder2ibek catio` from {chain.scanner_ioc}.
#
# The name_mappings below are the templates builder2ibek used to predict the new
# PV names when it rewrote every consumer's references. Editing them here
# without re-running the conversion will point those references at nothing.

controllers:
  - id: {chain.catio_ioc}
    type: {CATIO_CONTROLLER_TYPE}
    tcp_settings:
      target_ip: "REPLACE_WITH_ADS_SERVER_IP"
      target_port: 27905
    route:
      route_name: ""
      user_name: "Administrator"
      password: "1"
    scan_timings:
      poll_period: 1.0
      notification_period: 0.2
    name_mappings:
      device_prefix: "{mappings["device_prefix"]}"
      node_prefix: "{mappings["node_prefix"]}"
      module_prefix: "{mappings["module_prefix"]}"

transport:
  - epicsca: {{}}
    gui:
      output_dir: ./screens
      title: "{title} (from {chain.scanner_ioc})"
"""


def _fastcs_values_yaml(chain: Chain) -> str:
    """The ``values.yaml`` text for *chain*'s fastcs-catio IOC.

    ``stdio-expose`` rather than the scaffold's ``stdio-socket``: every FastCS
    IOC actually deployed uses the former (see the module report). The empty
    ``livenessExecutable``/``preStopExecutable`` come from the scaffold's own
    warning -- the FastCS image has none of ibek's probe executables.
    """
    del chain  # nothing instance-specific yet; kept for symmetry and future use
    run = f"{CATIO_ENTRYPOINT} run /epics/ioc/config/{FASTCS_CONFIG}"
    args = f"stdio-expose --ptty --stdin --ctrl-d '{run}'"
    return f"""\
# yaml-language-server: $schema=../../.helm-shared/values.schema.json

ioc-instance:
  image: {CATIO_IMAGE}:REPLACE_WITH_PINNED_TAG
  args:
    - {args}

  # the fastcs image has no ibek liveness/preStop executables
  livenessExecutable: ""
  preStopExecutable: ""
"""


def _placeholders(*texts: str) -> list[str]:
    """Every distinct ``REPLACE_WITH_*`` in *texts*, in order of first sighting.

    >>> _placeholders("a REPLACE_WITH_B c", "REPLACE_WITH_A, REPLACE_WITH_B")
    ['REPLACE_WITH_B', 'REPLACE_WITH_A']
    """
    found: dict[str, None] = {}
    for text in texts:
        for match in PLACEHOLDER_RE.findall(text):
            found[match] = None
    return list(found)


def write_catio_ioc(services_repo: Path, chain: Chain, *, dry_run: bool) -> list[str]:
    """Write the fastcs-catio IOC replacing *chain*'s legacy scanner.

    Scaffolds ``services/<chain.services_folder>`` from
    ``.fastcs_ioc_template``, writes ``config/fastcs.yaml`` and ``values.yaml``,
    and removes the scaffold's ``config/controller.yaml`` example so the folder
    holds exactly one FastCS config.

    :returns: the ``REPLACE_WITH_*`` placeholders a human must still fill in, in
        the order they appear in the generated files.
    """
    folder = scaffold(
        services_repo, chain.services_folder, fastcs=True, dry_run=dry_run
    )
    config = _fastcs_yaml(chain)
    values = _fastcs_values_yaml(chain)

    if not dry_run:
        config_dir = folder / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / FASTCS_CONFIG).write_text(config)
        (config_dir / FASTCS_EXAMPLE_CONFIG).unlink(missing_ok=True)
        (folder / "values.yaml").write_text(values)

    return _placeholders(config, values)


def write_ioc(
    services_repo: Path, ioc_name: str, ioc: Generic_IOC, *, dry_run: bool
) -> Path:
    """Write a converted ibek IOC into the services repo.

    Scaffolds ``services/<ioc_name.lower()>`` from ``.ioc_template`` and writes
    ``config/ioc.yaml``. ``values.yaml`` is deliberately left alone: on a fresh
    folder it keeps the template's ``REPLACE_WITH_IMAGE_URI`` (see
    :data:`IBEK_PLACEHOLDERS`), and on an existing folder it keeps the real
    image reference someone already pinned.

    ``ioc.schema.json`` is **not** written -- ``ibek pattern schema`` generates
    it from a pre-commit hook.

    :returns: the instance folder.
    """
    from builder2ibek.convert import write_ioc_yaml

    folder = scaffold(services_repo, ioc_name.lower(), fastcs=False, dry_run=dry_run)
    if not ioc.description:
        ioc.description = f"{ioc_name}, converted by builder2ibek catio"

    if not dry_run:
        # write_ioc_yaml mutates `ioc` (it drops the internal source_file
        # attribute), so it is called only on the writing path.
        write_ioc_yaml(ioc, folder / "config" / "ioc.yaml", IOC_SCHEMA)
    return folder


def read_sticky_ordinals(services_repo: Path) -> dict[str, int]:
    """The ``E{n}RIO`` ordinal of every fastcs-catio IOC already in the repo.

    Chain ordinals must be **sticky**: a second conversion run that renumbered
    a chain would repoint every PV rewritten by the first run at nothing. So
    the allocator in :func:`~builder2ibek.catio.chains.discover_chains` starts
    from whatever is on disk.

    Every ``services/*/config/fastcs.yaml`` is parsed; unrelated FastCS IOCs
    (a different controller ``type``, or the singular ``controller:`` mapping
    other FastCS projects use) and unparseable files are skipped silently --
    a services repo is entitled to hold FastCS IOCs this tool knows nothing
    about.

    :returns: ``{catio IOC id: ordinal}``.
    """
    yaml = YAML(typ="safe")
    ordinals: dict[str, int] = {}

    services = _services(services_repo)
    for path in sorted(services.glob(f"*/config/{FASTCS_CONFIG}")):
        try:
            doc = yaml.load(path)
        except (YAMLError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        controllers = doc.get("controllers")
        if not isinstance(controllers, list):
            continue
        for controller in controllers:
            entry = _ordinal_of(controller)
            if entry is not None:
                ordinals[entry[0]] = entry[1]
    return ordinals


def _ordinal_of(controller: object) -> tuple[str, int] | None:
    """``(id, ordinal)`` for a fastcs-catio controller entry, else ``None``."""
    if not isinstance(controller, dict):
        return None
    if controller.get("type") != CATIO_CONTROLLER_TYPE:
        return None
    catio_ioc = controller.get("id")
    if not isinstance(catio_ioc, str) or not catio_ioc:
        return None
    mappings = controller.get("name_mappings")
    if not isinstance(mappings, dict):
        return None
    node_prefix = mappings.get("node_prefix")
    if not isinstance(node_prefix, str):
        return None
    match = _ORDINAL_RE.search(node_prefix)
    if match is None:
        return None
    return catio_ioc, int(match.group(1))
