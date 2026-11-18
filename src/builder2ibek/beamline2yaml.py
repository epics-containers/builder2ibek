"""
Plan, and optionally write, ibek services folders for every BUILDER XML IOC of
a beamline: the deterministic part of a beamline conversion.

For each IOC XML in the beamline's BUILDER (work area, else the latest prod
release; macro-template XMLs are left out) the plan says what happens to
``services/<ioc>/``:

- ``add``: no folder yet; it is made from ``.ioc_template``.
- ``replace``: a dev-c7 legacy folder; it is made again from ``.ioc_template``.
- ``fastcs``: a dedicated PandA IOC; xml2yaml writes a fastcs-pandablocks
  instance in the folder (a legacy folder is converted in place).
- ``blocked``: an IOC that would be added or replaced but cannot run: it
  targets another OS or architecture (the XML's ``arch``, or its boot script),
  no generic IOC image builds it, or a module is unresolved. No folder is
  written, and a dev-c7 legacy folder is kept.
- ``skip``: an ibek folder (``reconvert`` handles those), a fastcs instance, a
  folder of another kind, or a PandA another instance already serves.
- ``error``: the XML does not convert.

Each IOC is planned on the entities xml2yaml writes: a beamline module's
entities its runtime pattern does not take are dropped, and reported, as
:func:`builder2ibek.convert.drop_unpatterned_entities` drops them. A
pattern-only IOC (:func:`~builder2ibek.vendor_patterns.is_pattern_only`) is
left to xml2yaml, which sets the latest ioc-streamdevice-runtime. Any other
IOC gets the smallest generic IOC in :data:`GENERIC_IMAGES` whose entity types
cover every entity that is not a runtime pattern, and that builds StreamDevice
for each StreamDevice pattern it does not install. The entity types come from
the image's published ioc schema, or, for a GitLab image that publishes none,
from the support YAMLs in this checkout of the modules its Dockerfile builds,
the models of the runtime patterns it installs with ``ibek pattern install``,
at the library release each pins, and ioc-generic's. Each IOC's modules are
reported as pattern, build-time or unresolved
(:func:`~builder2ibek.vendor_patterns.classify_modules`) against
the chosen image, and only the patterns that image does not install are
listed, as xml2yaml decides them.

Whether each IOC is live (in a DLS init launch list) is reported, not acted
on: every IOC in the BUILDER is planned. A live IOC's values.yaml gets the
dev-c7 warning to stop it on its server before deploying.

``--apply`` writes the folders, converts each IOC with xml2yaml, giving it the
chosen image (xml2yaml adds the runtime patterns), and schema-validates every
ioc.yaml with ``ibek runtime generate2`` in a temporary EPICS_ROOT, against
this checkout's support YAMLs, those the IOC vendors, and those of the
patterns its image installs. No IOC is started. It writes nothing when a step
of the plan failed: a pattern library that could not be indexed, a GitHub or
GitLab lookup, or no generic IOC schema at all. A legacy folder is moved aside
while its replacement is converted: when the conversion fails, the folder made
for it is removed and the legacy one put back. An IOC whose ioc.yaml fails the
schema check keeps its folder, and the validator's output is reported. The
services repo is a git repo: ``git status`` shows, and ``git checkout`` and
``git clean`` revert, what a run wrote.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import ssl
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import truststore
from ibek.pattern_cmds.sources import DEFAULT_LIBRARIES, PatternError, parse_ref
from ibek.support import support_yaml_module
from ruamel.yaml import YAML

from builder2ibek.builder import Builder
from builder2ibek.convert import (
    ConvertResult,
    convert_file,
    dispatch,
    drop_unpatterned_entities,
)
from builder2ibek.devc7 import (
    DLS_SW,
    INIT_DIR,
    REDIRECT_TABLE,
    _classify_os,
    _folder_kind,
    add_header,
    read_init,
    read_redirect_table,
    running_header,
)
from builder2ibek.fastcs_panda import CONTROLLER_YAML, plan_fastcs
from builder2ibek.patterns import (
    STREAMDEVICE_LIBRARY,
    Pattern,
    PatternPlan,
    latest_tag,
    library_release,
    pattern_index,
)
from builder2ibek.reconvert import (
    IOC_SCHEMA,
    REPO_ROOT,
    _is_template_xml,
    discover_xmls,
    normalize_beamline,
    validate_configs,
)
from builder2ibek.vendor_patterns import (
    ModuleStatus,
    PatternReport,
    SchemaUnavailableError,
    classify_modules,
    fetch_entity_types,
    image_entity_types,
    is_pattern_only,
    module_report,
    patterns_to_add,
    plan_patterns,
    runtime_image,
)

TEMPLATE = ".ioc_template"
GITLAB_TOKEN_ENV = "GITLAB_TOKEN"
LINUX_ARCH = "linux-x86_64"
# ansible.sh <module> [args], at the start of a RUN or after && (on the same
# line or a continuation line)
ANSIBLE_RE = re.compile(
    r"(?:^\s*RUN\s+|&&\s*(?:\\\s*)?)ansible\.sh\s+([^\s&\\]+)([^\n&]*)", re.M
)
# the arguments of an ``ibek pattern install`` in a Dockerfile whose line
# continuations are joined (see :func:`_join_continuations`)
INSTALL_RE = re.compile(r"\bibek\s+pattern\s+install\b([^\n&;|]*)")


class PlanFailedError(Exception):
    """A step of the plan failed, so --apply writes nothing."""


@dataclass(frozen=True)
class GenericImage:
    """A generic IOC a converted IOC can run on."""

    #: GitHub ``org/repo``, or GitLab project path when ``gitlab`` is set
    repo: str
    #: the image without its tag
    image: str
    #: the image builds StreamDevice, so StreamDevice patterns can run on it
    streamdevice: bool = False
    #: GitLab web host of ``repo``; its releases publish no ioc schema
    gitlab: str = ""


def _gh(name: str, streamdevice: bool = False) -> GenericImage:
    return GenericImage(
        f"epics-containers/{name}",
        f"ghcr.io/epics-containers/{name}-runtime",
        streamdevice,
    )


#: Linux generic IOCs, in order of preference when two cover an IOC equally.
#: StreamDevice is from each Dockerfile's ``ansible.sh StreamDevice``.
GENERIC_IMAGES: tuple[GenericImage, ...] = (
    _gh("ioc-generic"),
    _gh("ioc-streamdevice", streamdevice=True),
    _gh("ioc-pmac"),
    _gh("ioc-motorsim"),
    _gh("ioc-oxcryo", streamdevice=True),
    _gh("ioc-thermofht6020a", streamdevice=True),
    _gh("ioc-tetramm"),
    _gh("ioc-adaravis"),
    _gh("ioc-adsimdetector"),
    _gh("ioc-aduvc"),
    _gh("ioc-adzmq"),
    _gh("ioc-adandor"),
    _gh("ioc-adandor3"),
    _gh("ioc-slsdetector"),
    _gh("ioc-xspress3"),
    _gh("ioc-opcua"),
    _gh("ioc-terminalserver"),
    GenericImage(
        "controls/containers/iocs/ioc-dlslinuxvac",
        "gitlab.diamond.ac.uk:5050/controls/containers/iocs/ioc-dlslinuxvac/"
        "ioc-dlslinuxvac-linux-runtime",
        streamdevice=True,
        gitlab="gitlab.diamond.ac.uk",
    ),
)


@dataclass
class Candidate:
    """A generic IOC at its latest release, with the entity types it builds."""

    generic: GenericImage
    ref: str = ""  # image:tag, "" when no release was found
    types: frozenset[str] | None = None
    problem: str = ""  # why it cannot be matched, or what was guessed
    failed: bool = False  # a GitHub or GitLab lookup failed: --apply stops
    #: the runtime patterns the image installs, at the releases it pins
    installed: tuple[Pattern, ...] = ()
    #: install lines or references that could not be matched
    warnings: list[str] = field(default_factory=list)


def _gitlab_get(host: str, path: str) -> bytes:
    headers = {}
    token = os.getenv(GITLAB_TOKEN_ENV, "").strip()
    if token:
        headers["PRIVATE-TOKEN"] = token
    request = urllib.request.Request(f"https://{host}/api/v4/{path}", headers=headers)
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return response.read()


def _github_release(repo: str) -> str:
    """The tag of a GitHub repository's latest release, sending $GITHUB_TOKEN
    or $GH_TOKEN when set (anonymous requests are rate limited)."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest", headers=headers
    )
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return json.load(response)["tag_name"]


@cache
def support_models() -> dict[str, frozenset[str]]:
    """Support folder name -> the entity types its support YAML defines, from
    this checkout's ibek-support*."""
    models: dict[str, frozenset[str]] = {}
    yaml = YAML(typ="safe")
    for path in sorted(REPO_ROOT.glob("ibek-support*/*/*.ibek.support.yaml")):
        data = yaml.load(path.read_text()) or {}
        module = str(data.get("module") or path.parent.name)
        names = {
            f"{module}.{e['name']}"
            for e in data.get("entity_models") or []
            if isinstance(e, dict) and "name" in e
        }
        models[path.parent.name] = models.get(path.parent.name, frozenset()) | names
    return models


def _gitlab_file(generic: GenericImage, path: str, tag: str) -> str:
    project = urllib.parse.quote(generic.repo, safe="")
    return _gitlab_get(
        generic.gitlab,
        f"projects/{project}/repository/files/{urllib.parse.quote(path, safe='')}"
        f"/raw?ref={urllib.parse.quote(tag, safe='')}",
    ).decode()


def _join_continuations(dockerfile: str) -> str:
    """A Dockerfile with each ``\\`` line continuation joined to its line."""
    return re.sub(r"\\[ \t]*\r?\n", " ", dockerfile)


def _installed_patterns(
    generic: GenericImage, dockerfile: str, tag: str
) -> tuple[list[str], list[str]]:
    """The pattern references the Dockerfile's ``ibek pattern install`` lines
    install, those given on the line and those in each ``--list`` file, read
    from the repository at ``tag``; and a warning for each argument that is
    not understood."""
    refs: list[str] = []
    warnings: list[str] = []
    for args in INSTALL_RE.findall(_join_continuations(dockerfile)):
        words = iter(args.split())
        for word in words:
            option, eq, value = word.partition("=")
            if option in ("--list", "-l", "--source", "-s"):
                value = value if eq else next(words, "")
                if option in ("--source", "-s"):
                    warnings.append(
                        f"ibek pattern install --source {value}: its patterns "
                        f"are matched against the libraries they name"
                    )
                    continue
                for line in _gitlab_file(generic, value, tag).splitlines():
                    line = line.partition("#")[0].strip()
                    if line:
                        refs.append(line)
            elif word.startswith("-"):
                warnings.append(f"ibek pattern install: unknown option {word}")
            else:
                refs.append(word)
    return refs, warnings


def _resolve_installed(refs: Iterable[str]) -> tuple[list[Pattern], list[str]]:
    """The patterns ``refs`` name, each from its library at the release the
    reference pins, and a warning for each reference that names none.

    Raises PatternIndexError when a library release cannot be cloned.
    """
    patterns: list[Pattern] = []
    warnings: list[str] = []
    for text in refs:
        try:
            ref = parse_ref(text)
        except PatternError:
            ref = None
        if ref is None or not ref.library or not ref.version:
            warnings.append(
                f"installed pattern {text!r} is not library:module@version: not matched"
            )
            continue
        if ref.library not in DEFAULT_LIBRARIES:
            warnings.append(
                f"installed pattern {text}: unknown library {ref.library}, not matched"
            )
            continue
        pattern = library_release(ref.library, ref.version).patterns.get(ref.name)
        if pattern is None:
            warnings.append(
                f"installed pattern {text}: {ref.library} {ref.version} has no "
                f"pattern {ref.name}, not matched"
            )
            continue
        patterns.append(pattern)
    return patterns, warnings


def _pattern_types(patterns: Iterable[Pattern]) -> frozenset[str]:
    """The entity types of ``patterns``, from their models."""
    return frozenset(f"{p.module}.{model}" for p in patterns for model in p.models)


def _gitlab_candidate(
    generic: GenericImage, base: frozenset[str], tag: str | None = None
) -> Candidate:
    """Entity types of a GitLab generic IOC at ``tag``, else its latest
    release: those of the modules its Dockerfile builds with ``ansible.sh``,
    of the runtime patterns it installs with ``ibek pattern install``, and the
    ``base`` types every generic IOC has (ioc-generic's)."""
    cand = Candidate(generic)
    if not base:
        cand.problem = (
            "ioc-generic's ioc schema is unavailable, so the base types every "
            "generic IOC has are missing"
        )
        cand.failed = True
        return cand
    project = urllib.parse.quote(generic.repo, safe="")
    try:
        if tag is None:
            latest = json.loads(
                _gitlab_get(
                    generic.gitlab, f"projects/{project}/releases/permalink/latest"
                )
            )
            tag = str(latest["tag_name"])
        dockerfile = _gitlab_file(generic, "Dockerfile", tag)
        installed, cand.warnings = _installed_patterns(generic, dockerfile, tag)
    except Exception as e:  # noqa: BLE001 -- unreachable, no token, no release
        cand.problem = (
            f"cannot read its release, Dockerfile and pattern lists from "
            f"{generic.gitlab} (set {GITLAB_TOKEN_ENV}): {e}"
        )
        cand.failed = True
        return cand
    cand.ref = f"{generic.image}:{tag}"
    models = support_models()
    types = set(base)
    for name, rest in ANSIBLE_RE.findall(dockerfile):
        if "--tags" not in rest:
            types |= models.get(name, frozenset())
    if installed:
        try:
            patterns, warnings = _resolve_installed(installed)
        except Exception as e:  # noqa: BLE001 -- a library release not cloned
            cand.problem = f"the patterns it installs are not known: {e}"
            cand.failed = True
            return cand
        cand.installed = tuple(patterns)
        cand.warnings += warnings
        types |= _pattern_types(patterns)
    cand.types = frozenset(types)
    return cand


def _github_candidate(generic: GenericImage) -> Candidate:
    cand = Candidate(generic)
    try:
        tag = _github_release(generic.repo)
    except Exception as e:  # noqa: BLE001 -- rate limit, unreachable, ...
        cand.failed = True
        try:
            tag = latest_tag(f"https://github.com/{generic.repo}")
        except Exception:  # noqa: BLE001
            cand.problem = f"no latest release: {e}"
            return cand
        cand.problem = (
            f"latest release unreadable ({e}); used its highest tag {tag}, "
            f"set GITHUB_TOKEN to read releases"
        )
    cand.ref = f"{generic.image}:{tag}"
    try:
        cand.types = fetch_entity_types(cand.ref)
    except SchemaUnavailableError as e:
        # a release whose schema cannot be fetched is not one with none
        cand.failed = True
        cand.problem = cand.problem or str(e)
        return cand
    if cand.types is None:
        cand.problem = cand.problem or f"no published ioc schema for {cand.ref}"
    return cand


def _base_types(found: Iterable[Candidate]) -> frozenset[str]:
    """The types every generic IOC has: ioc-generic's."""
    return next(
        (c.types for c in found if c.generic.repo.endswith("/ioc-generic") and c.types),
        frozenset(),
    )


@cache
def candidates() -> tuple[Candidate, ...]:
    """Every generic IOC in GENERIC_IMAGES at its latest release."""
    found = [_github_candidate(g) for g in GENERIC_IMAGES if not g.gitlab]
    base = _base_types(found)
    found += [_gitlab_candidate(g, base) for g in GENERIC_IMAGES if g.gitlab]
    return tuple(found)


def gitlab_image_types(image: str) -> tuple[frozenset[str] | None, str]:
    """The entity types beamline2yaml matches a GitLab generic IOC of
    GENERIC_IMAGES on, at the tag ``image`` names, and a problem ("" if none).

    (None, "") for any other image, whose published schema says what it
    builds. Lets ``xml2yaml --image`` decide as beamline2yaml does.
    """
    name, _, tag = image.rpartition(":")
    generic = next((g for g in GENERIC_IMAGES if g.gitlab and g.image == name), None)
    if generic is None or "/" in tag:
        return None, ""
    base_image = next(g for g in GENERIC_IMAGES if g.repo.endswith("/ioc-generic"))
    cand = _gitlab_candidate(generic, _base_types([_github_candidate(base_image)]), tag)
    return cand.types, "; ".join(filter(None, [cand.problem, *cand.warnings]))


@dataclass
class ImageChoice:
    image: str = ""  # "" leaves the placeholder
    pattern_only: bool = False  # xml2yaml sets the runtime image
    types: frozenset[str] | None = None  # the chosen image's entity types
    missing: list[str] = field(default_factory=list)  # with no image
    detail: str = ""
    # with no image: the candidate that builds the most, and its types
    closest: str = ""
    closest_types: frozenset[str] | None = None


def choose_image(
    entities: Sequence[Mapping[str, Any]],
    plan: PatternPlan,
    runtime_types: frozenset[str] | None,
    cands: Sequence[Candidate],
) -> ImageChoice:
    """The generic IOC for an IOC's ``entities``, whose patterns are ``plan``.

    ``runtime_types`` are the ioc-streamdevice-runtime image's entity types,
    None if unknown. Decides as xml2yaml does (see builder2ibek.vendor_patterns):
    a pattern-only IOC runs on the runtime image; on any other image, the
    patterns the image installs are left out, and every other StreamDevice
    pattern needs StreamDevice in the image.
    """
    if runtime_types is not None and is_pattern_only(entities, plan, runtime_types):
        return ImageChoice(
            pattern_only=True, types=runtime_types, detail="pattern-only"
        )
    pattern_modules = {p.module: p.library for p in plan.patterns}
    types = {str(e["type"]) for e in entities}
    needed = {t for t in types if t.partition(".")[0] not in pattern_modules}
    streamdevice: dict[str, set[str]] = {}
    for t in types:
        if pattern_modules.get(t.partition(".")[0]) == STREAMDEVICE_LIBRARY:
            streamdevice.setdefault(t.partition(".")[0], set()).add(t)

    def fits(c: Candidate) -> bool:
        assert c.types is not None
        return needed <= c.types and all(
            c.generic.streamdevice or used <= c.types for used in streamdevice.values()
        )

    usable = [c for c in cands if c.types is not None and c.ref]
    matching = [c for c in usable if fits(c)]
    if matching:
        best = min(matching, key=lambda c: (len(c.types or ()), usable.index(c)))
        return ImageChoice(image=best.ref, types=best.types)
    if not usable:
        return ImageChoice(detail="no generic IOC schema available", missing=[])
    closest = min(
        usable,
        key=lambda c: (len(needed - (c.types or frozenset())), usable.index(c)),
    )
    missing = sorted(needed - (closest.types or frozenset()))
    detail = f"no generic IOC builds every type; closest {closest.ref}"
    if not missing and streamdevice and not closest.generic.streamdevice:
        detail += ", which has no StreamDevice for the patterns"
    return ImageChoice(
        missing=missing,
        detail=detail,
        closest=closest.ref,
        closest_types=closest.types,
    )


@dataclass
class Entry:
    ioc: str
    xml: str
    folder: str
    action: str  # add, replace, fastcs, blocked, skip, error
    reason: str = ""
    image: str = ""
    pattern_only: bool = False  # xml2yaml sets the runtime image
    patterns: list[str] = field(default_factory=list)
    #: how each module runs: pattern, build-time or unresolved
    modules: list[ModuleStatus] = field(default_factory=list)
    live: str = ""  # init launch list servers, or why it is not live
    header: str = ""  # values.yaml warning for a live IOC
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = ""  # after --apply: ok, fastcs, refused, error
    #: after --apply: ok or fail, from ibek runtime generate2: the ioc.yaml
    #: matches the schema, not that the IOC can be deployed
    schema: str = ""
    schema_error: str = ""


@dataclass
class Plan:
    beamline: str
    services_repo: str
    builder_xml_dir: str
    source: str
    entries: list[Entry] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    #: what could not be matched of the generic IOCs' pattern installs
    image_warnings: list[str] = field(default_factory=list)
    #: steps that failed, so --apply writes nothing
    failures: list[str] = field(default_factory=list)


def _liveness(
    ioc: str,
    launches: Mapping[str, list[Any]],
    redirect: Mapping[str, list[tuple[str, str]]],
    folder: str,
) -> tuple[str, str, str]:
    """(live description, values.yaml header, OS reason) for an IOC; the OS
    reason, from its boot script, is "" for a Linux IOC."""
    boot = redirect[ioc][0][0] if ioc in redirect else ""
    why = _classify_os(boot) if boot else None
    os_reason = why if why and _is_os_reason(why) else ""
    os_note = f"; {why}" if why else ""
    if ioc in launches:
        servers = ", ".join(e.server for e in launches[ioc])
        return (
            f"live on {servers}{os_note}",
            running_header(launches[ioc], folder),
            os_reason,
        )
    if boot:
        return f"not live: retired (redirect table only){os_note}", "", os_reason
    return "not live: in no launch list or redirect table", "", ""


def _is_os_reason(why: str) -> bool:
    """True if a devc7._classify_os reason is another OS or architecture."""
    return why.startswith(("Windows", "vxWorks", "RTEMS")) or " target," in why


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _plan_entry(
    xml: Path,
    services: Path,
    entry: Entry,
    cands: Callable[[], Sequence[Candidate]],
    description: str,
    os_reason: str = "",
) -> None:
    """Fill in the action, image, patterns and modules of an IOC with no ibek
    folder, from the entities xml2yaml would write."""
    yaml = services / entry.folder / "config" / "ioc.yaml"
    builder = Builder()
    builder.load(xml)
    blockers: list[str] = []
    if builder.arch != LINUX_ARCH:
        blockers.append(f"{builder.arch} IOC, not runnable in a Linux container")
    elif os_reason:
        blockers.append(os_reason)
    with contextlib.redirect_stdout(sys.stderr):
        ioc = dispatch(builder, xml, yaml.parent, description=description)
        # as convert_file drops them; raises BeamlinePatternError like it
        drop_unpatterned_entities(ioc)
    split = ioc.panda_split
    if split is not None:
        fastcs = plan_fastcs(xml.stem, split, yaml)
        entry.warnings += fastcs.refusals
        entry.notes += [
            f"fastcs-pandablocks instance {t.folder.name} for "
            + ", ".join(p.prefix for p in t.pandas)
            for t in fastcs.targets
        ]
        if split.dedicated:
            if fastcs.refused:
                entry.action, entry.reason = "skip", "PandA served by another instance"
            else:
                entry.action = "fastcs"
            return
        if fastcs.ioc_yaml_refused:
            entry.action, entry.reason = "skip", "folder is a fastcs instance"
            return
    entry.warnings += ioc.warnings()

    entities = [dict(e) for e in ioc.entities]
    report = PatternReport()
    pattern_plan = plan_patterns(entities, report)
    entry.warnings += report.warnings
    runtime, _ = runtime_image()
    choice = choose_image(entities, pattern_plan, image_entity_types(runtime), cands())
    if choice.pattern_only:
        entry.image, entry.pattern_only = runtime, True
        entry.notes.append("pattern-only: xml2yaml sets the runtime image")
    elif choice.image:
        entry.image = choice.image
    else:
        blockers.append(
            f"no generic IOC image ({choice.detail}"
            + (f"; missing {', '.join(choice.missing)}" if choice.missing else "")
            + ")"
        )
    # with no image, against the closest one, so that what it lacks shows
    entry.modules = classify_modules(
        entities,
        pattern_plan,
        entry.image or choice.closest or None,
        choice.types if entry.image else choice.closest_types,
    )
    entry.warnings += module_report(entry.modules)[1]
    entry.patterns = [
        p.ref for p in patterns_to_add(entities, pattern_plan, choice.types)
    ]
    unresolved = [s.module for s in entry.modules if s.kind == "unresolved"]
    if unresolved:
        blockers.append("unresolved modules " + ", ".join(unresolved))
    if blockers:
        kept = "; dev-c7 legacy folder kept" if entry.action == "replace" else ""
        entry.action, entry.reason = "blocked", "; ".join(blockers) + kept
    entry.warnings = _dedupe(entry.warnings)


def build_plan(
    prefix: str,
    services_repo: Path,
    *,
    only: list[str] | None = None,
    descriptions: Mapping[str, str] | None = None,
    init_dir: Path | None = None,
    redirect_table: Path | None = None,
    dls_sw: Path = DLS_SW,
) -> Plan:
    beamline = normalize_beamline(prefix)
    services = services_repo / "services"
    if not services.is_dir():
        raise FileNotFoundError(f"{services} not found")
    xmls, source_dir, source = discover_xmls(beamline)
    if not xmls:
        raise FileNotFoundError(f"no BUILDER XMLs found for {beamline} in work or prod")
    init_dir = init_dir or dls_sw / INIT_DIR.relative_to(DLS_SW)
    redirect_table = redirect_table or dls_sw / REDIRECT_TABLE.relative_to(DLS_SW)
    launches = read_init(init_dir) if init_dir.is_dir() else {}
    redirect = read_redirect_table(redirect_table) if redirect_table.is_file() else {}
    only_set = {n.lower() for n in only or []}
    descriptions = descriptions or {}

    plan = Plan(beamline, str(services_repo), str(source_dir), source)
    for xml in xmls:
        if _is_template_xml(xml):
            continue
        ioc = xml.stem
        folder = ioc.lower()
        if only_set and folder not in only_set:
            continue
        entry = Entry(ioc, str(xml), folder, "add")
        plan.entries.append(entry)
        entry.live, entry.header, os_reason = _liveness(ioc, launches, redirect, folder)
        path = services / folder
        if os.path.lexists(path):
            kind = _folder_kind(path)
            if (path / "config" / CONTROLLER_YAML).is_file():
                entry.action, entry.reason = "skip", "fastcs instance exists"
                continue
            if kind == "ibek":
                entry.action, entry.reason = "skip", "ibek folder: use reconvert"
                continue
            if kind != "dev-c7 legacy" or path.is_symlink():
                entry.action, entry.reason = "skip", f"folder exists ({kind})"
                continue
            entry.action = "replace"
        try:
            _plan_entry(
                xml,
                services,
                entry,
                candidates,
                descriptions.get(folder, ""),
                os_reason,
            )
        except Exception as e:  # noqa: BLE001 -- report any converter error
            entry.action, entry.reason = "error", f"{type(e).__name__}: {e}"
    plan.failures = _failures(plan)
    return plan


def _failures(plan: Plan) -> list[str]:
    """The steps of the plan that failed, which --apply refuses to build on."""
    failures: list[str] = []
    try:
        index = pattern_index()
    except Exception as e:  # noqa: BLE001 -- any failure to index
        failures.append(f"runtime pattern libraries not indexed: {e}")
    else:
        failures += [
            f"{library} not indexed: {error}"
            for library, error in index.failures.items()
        ]
    runtime, warning = runtime_image()
    if warning:
        failures.append(warning)
    try:
        # decides which IOCs are pattern-only
        if fetch_entity_types(runtime) is None:
            failures.append(f"no published ioc schema for {runtime}")
    except SchemaUnavailableError as e:
        failures.append(str(e))
    if any(e.action in ("add", "replace", "blocked") for e in plan.entries):
        cands = candidates()
        plan.images = [
            {"image": c.ref or c.generic.image, "problem": c.problem}
            for c in cands
            if c.problem
        ]
        plan.image_warnings = [
            f"{c.ref or c.generic.image}: {w}" for c in cands for w in c.warnings
        ]
        failures += [
            f"{c.ref or c.generic.image}: {c.problem}" for c in cands if c.failed
        ]
        if not any(c.types is not None and c.ref for c in cands):
            failures.append("no generic IOC has a usable ioc schema")
    services = Path(plan.services_repo) / "services"
    failures += [
        f"{backup} is left from an interrupted --apply: move it back to "
        f"{services / e.folder} or remove it"
        for e in plan.entries
        if os.path.lexists(backup := backup_path(services, e.folder))
    ]
    return failures


def backup_path(services: Path, folder: str) -> Path:
    """Where --apply keeps a legacy folder while its replacement is converted."""
    return services / f".{folder}.beamline2yaml-backup"


def _make_folder(services: Path, entry: Entry) -> None:
    """Make an IOC's folder from .ioc_template with its values.yaml header."""
    folder = services / entry.folder
    shutil.copytree(services / TEMPLATE, folder, symlinks=True)
    values = folder / "values.yaml"
    values.write_text(add_header(values.read_text(), entry.header))


def _restore(folder: Path, backup: Path | None) -> None:
    """Remove a folder written for a conversion, and put back the legacy
    folder it replaced."""
    shutil.rmtree(folder, ignore_errors=True)
    if backup is not None:
        backup.rename(folder)


def _conversion_problem(entry: Entry, result: ConvertResult) -> str:
    """Why a conversion that raised nothing still failed, or ""."""
    if entry.action != "fastcs" and not result.ioc_yaml_written:
        why = "a PandA another instance serves" if result.refused else "fastcs"
        return f"no ioc.yaml written ({why})"
    if result.pattern_errors:
        return "; ".join(result.pattern_errors)
    return ""


class ConversionFailedError(Exception):
    """A conversion that returned, but did not do all it had to."""


def _image_candidate(image: str) -> Candidate | None:
    return next((c for c in candidates() if c.ref == image), None)


def _installed_support_yamls(entry: Entry, config: Path) -> list[Path]:
    """The support YAMLs of the patterns an IOC's image installs, at the
    releases it pins, for the modules its config does not vendor: the image
    has them in its ibek-defs, which this checkout's schema does not."""
    if not entry.image or entry.pattern_only:
        return []
    cand = _image_candidate(entry.image)
    if cand is None or not cand.installed:
        return []
    vendored = {
        support_yaml_module(path) for path in config.rglob("*.ibek.support.yaml")
    }
    return [p.support_yaml for p in cand.installed if p.module not in vendored]


def apply_plan(
    plan: Plan, descriptions: Mapping[str, str] | None = None, validate: bool = True
) -> None:
    """Write and convert the planned folders. Raises PlanFailedError, writing
    nothing, when a step of the plan failed.

    An IOC whose conversion fails has status "error": the folder made for it
    is removed and the legacy folder it replaced is put back. With
    ``validate``, an IOC whose ioc.yaml fails the schema check keeps its
    folder, and entry.schema_error says why.
    """
    if plan.failures:
        raise PlanFailedError(
            "not applied, as a step of the plan failed: " + "; ".join(plan.failures)
        )
    services = Path(plan.services_repo) / "services"
    if not (services / TEMPLATE / "values.yaml").is_file():
        raise FileNotFoundError(f"{services / TEMPLATE}/values.yaml not found")
    descriptions = descriptions or {}
    by_name = {e.ioc: e for e in plan.entries}
    configs: dict[str, Path] = {}
    for entry in plan.entries:
        if entry.action in ("add", "replace", "fastcs"):
            _apply_entry(services, entry, descriptions)
            if entry.status == "ok":
                configs[entry.ioc] = services / entry.folder / "config"
    if validate and configs:
        support_yamls = {
            ioc: _installed_support_yamls(by_name[ioc], config)
            for ioc, config in configs.items()
        }
        for v in validate_configs(configs, support_yamls):
            entry = by_name[v["ioc_name"]]
            entry.schema = v["status"]
            entry.schema_error = v.get("stderr", "")


def _apply_entry(services: Path, entry: Entry, descriptions: Mapping[str, str]) -> None:
    """Write and convert one IOC's folder, and set entry.status. After a
    failed conversion the folder made for it is removed and the legacy folder
    it replaced is back in place; xml2yaml alone writes a fastcs instance, so
    nothing is put back for one."""
    folder = services / entry.folder
    yaml = folder / "config" / "ioc.yaml"
    image, image_types = None, None
    if entry.image and not entry.pattern_only:
        image = entry.image
        cand = _image_candidate(entry.image)
        image_types = cand.types if cand is not None else None
    made, backup = False, None
    try:
        if entry.action != "fastcs":
            if entry.action == "replace":
                backup = backup_path(services, entry.folder)
                folder.rename(backup)
            made = True
            _make_folder(services, entry)
        with contextlib.redirect_stdout(sys.stderr):
            result = convert_file(
                Path(entry.xml),
                yaml,
                IOC_SCHEMA,
                description=descriptions.get(entry.folder, ""),
                image=image,
                image_types=image_types,
            )
        problem = _conversion_problem(entry, result)
        if problem:
            raise ConversionFailedError(problem)
    except Exception as e:  # noqa: BLE001 -- report any converter error
        if made:
            _restore(folder, backup)
        entry.status = "error"
        put_back = "; the dev-c7 legacy folder is put back" if backup else ""
        entry.warnings.append(f"conversion failed: {type(e).__name__}: {e}{put_back}")
        return
    if backup is not None:
        shutil.rmtree(backup)
    # the conversion's module report replaces the plan's: its notes are
    # rendered from entry.modules, its unresolved modules are warnings
    old_warnings = module_report(entry.modules)[1]
    notes = module_report(result.modules)[0]
    if result.modules:
        entry.modules = result.modules
    entry.notes = _dedupe([*entry.notes, *(n for n in result.notes if n not in notes)])
    entry.warnings = _dedupe(
        [*(w for w in entry.warnings if w not in old_warnings), *result.warnings]
    )
    if result.ioc_yaml_written:
        entry.status = "ok"
    else:
        entry.status = "refused" if result.refused else "fastcs"
        values = folder / "values.yaml"
        if entry.header and values.is_file():
            text = values.read_text()
            if entry.header.split(".")[0] not in text.replace("\n# ", " "):
                values.write_text(add_header(text, entry.header))


def _status(e: Entry) -> str:
    """An applied entry's outcome: what was written, whether the ioc.yaml
    matches the schema, and anything that still keeps it from running."""
    parts = [e.status]
    if e.schema:
        parts.append(f"schema {e.schema}")
    if not e.image and e.status == "ok":
        parts.append("no image")
    unresolved = [s.module for s in e.modules if s.kind == "unresolved"]
    if unresolved:
        parts.append("unresolved " + ", ".join(unresolved))
    return "[" + "; ".join(parts) + "]"


def render_plan(plan: Plan, applied: bool) -> str:
    out = [
        f"beamline2yaml {plan.beamline} -> {plan.services_repo}",
        f"BUILDER XMLs: {plan.source} {plan.builder_xml_dir}",
        "",
    ]
    rows = [("IOC", "ACTION", "IMAGE", "DETAIL")]
    for e in plan.entries:
        detail = e.reason or e.live
        if applied and e.status:
            detail = f"{_status(e)} {e.live}"
        rows.append((e.ioc, e.action, e.image or "-", detail))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for row in rows:
        out.append(
            "  ".join(c.ljust(w) for c, w in zip(row[:3], widths, strict=True))
            + "  "
            + row[3]
        )
    patterns = [(e.ioc, p) for e in plan.entries for p in e.patterns]
    if patterns:
        out += ["", "runtime patterns:"]
        out += [f"  {ioc}: {p}" for ioc, p in patterns]
    modules = [(e.ioc, _modules_line(e.modules)) for e in plan.entries if e.modules]
    if modules:
        out += ["", "modules:"]
        out += [f"  {ioc}: {line}" for ioc, line in modules]
    for title, attr in (("notes", "notes"), ("warnings", "warnings")):
        items = [(e.ioc, n) for e in plan.entries for n in getattr(e, attr)]
        if items:
            out += ["", f"{title}:"]
            # a conversion warning may already name the IOC
            out += [
                f"  {ioc}: " + n.removeprefix(f"{ioc}: ").replace("\n", "\n    ")
                for ioc, n in items
            ]
    failed = [e for e in plan.entries if e.schema == "fail"]
    if failed:
        out += ["", "schema validation failures:"]
        for e in failed:
            out.append(f"  {e.ioc}:")
            out += [f"      {line}" for line in e.schema_error.splitlines()]
    if plan.images:
        out += ["", "generic IOCs not matched:"]
        out += [f"  {i['image']}: {i['problem']}" for i in plan.images]
    if plan.image_warnings:
        out += ["", "generic IOC warnings:"]
        out += [f"  {w}" for w in plan.image_warnings]
    if plan.failures:
        out += ["", "failed steps (--apply writes nothing until they succeed):"]
        out += [f"  {f}" for f in plan.failures]
    todo = sum(e.action in ("add", "replace", "fastcs") for e in plan.entries)
    blocked = sum(e.action == "blocked" for e in plan.entries)
    verb = "converted" if applied else "to convert (dry run; --apply writes them)"
    out += ["", f"{todo} IOC(s) {verb}, {blocked} blocked"]
    return "\n".join(out)


def _modules_line(statuses: Sequence[ModuleStatus]) -> str:
    """One line listing an IOC's modules by kind; unresolved ones are also
    warnings, with their reasons."""
    kinds: dict[str, list[str]] = {}
    for status in statuses:
        kinds.setdefault(status.kind, []).append(status.module)
    return "; ".join(
        f"{kind}: {', '.join(kinds[kind])}"
        for kind in ("pattern", "build-time", "unresolved")
        if kind in kinds
    )


def beamline2yaml_cli(
    prefix: str,
    services_repo: Path,
    *,
    apply: bool = False,
    validate: bool = True,
    only: list[str] | None = None,
    descriptions_json: Path | None = None,
    json_out: bool = False,
    init_dir: Path | None = None,
    redirect_table: Path | None = None,
    dls_sw: Path = DLS_SW,
) -> int:
    """Exit codes: 0 clean, 1 bad input or a failed plan step with --apply,
    2 conversion errors, 3 schema validation failures."""
    try:
        descriptions: dict[str, str] = {}
        if descriptions_json is not None:
            raw = json.loads(descriptions_json.read_text())
            if not isinstance(raw, dict):
                raise ValueError("--descriptions-json must hold a JSON object")
            descriptions = {str(k).lower(): str(v) for k, v in raw.items()}
        plan = build_plan(
            prefix,
            services_repo,
            only=only,
            descriptions=descriptions,
            init_dir=init_dir,
            redirect_table=redirect_table,
            dls_sw=dls_sw,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    code = 0
    if apply:
        try:
            apply_plan(plan, descriptions, validate=validate)
        except (OSError, ValueError, PlanFailedError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            code = 1
    if json_out:
        print(json.dumps(asdict(plan), indent=2))
    else:
        print(render_plan(plan, apply and not code))
    if code:
        return code
    if any(e.action == "error" or e.status == "error" for e in plan.entries):
        return 2
    if any(e.schema == "fail" for e in plan.entries):
        return 3
    return 0
