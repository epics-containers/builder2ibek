"""Write a beamline's Phoebus hardware status screen from its services repo.

``builder2ibek hardware-status <services-repo>`` reads
``synoptic/hardware-status/hardware-status.yaml`` in the services repo and
writes ``hardware-status.bob`` next to it, from what is deployed:

- one row per IOC instance in ``services/`` (ibek, dev-c7 or fastcs), plus the
  IOCs listed under ``external:`` in the yaml
- GeoBricks, PLCs, RGAs, crate monitors and rack fans read from the entities in
  each ibek IOC's ``config/ioc.yaml``

Every status widget is alarm sensitive, so a stopped IOC shows as disconnected.
Buttons open the ``index.bob`` each IOC publishes on the opis server, found
relative to the screen through the yaml's ``opis_root`` (default ``../..``,
for a screen published at ``<opis>/<service>/hardware-status/``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from ruamel.yaml import YAML

SCREEN_DIR = Path("synoptic") / "hardware-status"
CONFIG_NAME = "hardware-status.yaml"
OUTPUT_NAME = "hardware-status.bob"
DEFAULT_OPIS_ROOT = "../.."

ROW = 25
GAP = 10
TITLE_H = 40

SEVERITY_COLOURS = [
    ("NO_ALARM", (0, 200, 0)),
    ("MINOR", (255, 200, 0)),
    ("MAJOR", (255, 0, 0)),
    ("INVALID", (255, 0, 255)),
]

DEVICE_GROUPS = ["GeoBricks", "PLCs", "RGAs", "Crate monitors", "Rack fans and PSUs"]


@dataclass
class Ioc:
    name: str  # IOC name in upper case, also its iocStats prefix
    service: str | None  # services folder, or None for an external IOC
    kind: str  # ibek, dev-c7, fastcs or a description for external IOCs
    label: str
    load_pv: str | None = None  # CPU load record, for the severity LED
    autosave: str | None = None  # save_restoreStatus prefix


@dataclass
class Device:
    group: str
    label: str
    service: str
    leds: list[tuple[str, str]] = field(default_factory=list)  # (tooltip, pv)
    text_pv: str | None = None


# ---------------------------------------------------------------- reading


def _load_yaml(path: Path) -> Any:
    return YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))


def load_entities(ioc_yaml: Path) -> list[dict]:
    # ioc.yaml holds Jinja in string values only, so plain YAML reads it
    data = _load_yaml(ioc_yaml) or {}
    return [
        e
        for e in data.get("entities", [])
        if isinstance(e, dict) and str(e.get("entity_enabled", True)).lower() != "false"
    ]


def iocstats_name(entities: list[dict], service: str) -> str:
    for e in entities:
        if e.get("type") == "devIocStats.iocAdminSoft":
            ioc = str(e.get("IOC", ""))
            if "ioc_name" not in ioc:
                return ioc
    return service.upper()


def read_services(services: Path, conf: dict) -> tuple[list[Ioc], list[Device]]:
    labels = conf.get("labels") or {}
    skip = conf.get("skip") or []
    iocs: list[Ioc] = []
    devices: list[Device] = []
    prefixes = tuple(conf["beamline_services"])

    for folder in sorted(services.iterdir()):
        service = folder.name
        if not folder.is_dir() or not service.startswith(prefixes):
            continue
        if service in skip:
            continue
        ioc_yaml = folder / "config" / "ioc.yaml"
        fastcs_yaml = folder / "config" / "fastcs.yaml"
        values = folder / "values.yaml"

        if ioc_yaml.exists():
            entities = load_entities(ioc_yaml)
            name = iocstats_name(entities, service)
            ioc = Ioc(name, service, "ibek", labels.get(name, ""))
            ioc.load_pv = f"{name}:IOC_CPU_LOAD"
            for e in entities:
                if e.get("type") == "autosave.Autosave":
                    ioc.autosave = str(e.get("P", f"{name}:"))
            devices += read_devices(entities, service)
            iocs.append(ioc)
        elif fastcs_yaml.exists():
            name = service.upper()
            iocs.append(Ioc(name, service, "fastcs", labels.get(name, "")))
        elif values.exists() and re.search(
            r"^dev-c7:", values.read_text(encoding="utf-8"), re.M
        ):
            # a legacy IOC: DLS iocStats, prefixed by the IOC name; its builder
            # IOC loads no save_restoreStatus records, so no autosave LED
            name = service.upper()
            ioc = Ioc(name, service, "dev-c7", labels.get(name, ""))
            ioc.load_pv = f"{name}:LOAD"
            iocs.append(ioc)

    in_k8s = {i.name for i in iocs}
    for ext in conf.get("external") or []:
        name = ext["name"]
        if name in in_k8s:
            continue
        ioc = Ioc(name, None, ext.get("kind", "external"), labels.get(name, ""))
        ioc.load_pv = f"{name}:LOAD"
        iocs.append(ioc)

    return iocs, devices


def read_devices(entities: list[dict], service: str) -> list[Device]:
    devices: list[Device] = []
    mstops = {
        str(e.get("P")) for e in entities if e.get("type") == "pmac.GeoBricketteMStop"
    }
    for e in entities:
        kind = e.get("type", "")
        if kind == "pmac.GeoBrick":
            p = str(e["P"])
            d = Device("GeoBricks", p, service)
            d.leds.append(("CPU load (severity)", f"SEVR:{p}:CPULOAD_0"))
            if p in mstops:
                d.leds.append(("Motion stop", f"BOOL:{p}:MOTIONSTOP:RBV"))
                d.leds.append(("Motion stop active", f"BOOL:{p}:MOTIONSTOP_ACTIVE:RBV"))
            devices.append(d)
        elif kind == "FINS.FINSTemplate":
            p = str(e["device"])
            devices.append(Device("PLCs", p, service, text_pv=f"{p}:MODE"))
        elif kind.startswith("rgamv2."):
            p = str(e["device"])
            devices.append(Device("RGAs", p, service, [("Status", f"SEVR:{p}:STA")]))
        elif kind == "CrateMonitor.CrateMonitor":
            p = str(e["device"])
            devices.append(
                Device("Crate monitors", p, service, [("Status", f"SEVR:{p}:STATUS")])
            )
        elif kind.startswith("rackFan."):
            p = str(e["device"])
            text = f"{p}  {e.get('DESC', '')}".strip()
            devices.append(
                Device(
                    "Rack fans and PSUs", text, service, [("Status", f"SEVR:{p}:STA")]
                )
            )
    return devices


# ---------------------------------------------------------------- writing


def colour(name: str, rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f'<color name="{name}" red="{r}" green="{g}" blue="{b}"></color>'


def geometry(x: int, y: int, w: int, h: int) -> str:
    return f"<x>{x}</x><y>{y}</y><width>{w}</width><height>{h}</height>"


def label(text: str, x: int, y: int, w: int, bold: bool = False) -> str:
    font = (
        '<font><font family="Liberation Sans" style="BOLD" size="14.0"></font></font>'
        if bold
        else ""
    )
    return (
        f'<widget type="label" version="2.0.0"><name>Label</name>'
        f"<text>{escape(text)}</text>{geometry(x, y, w, 20)}{font}"
        f"<vertical_alignment>1</vertical_alignment></widget>"
    )


def text_update(pv: str, x: int, y: int, w: int) -> str:
    return (
        f'<widget type="textupdate" version="2.0.0"><name>{escape(pv)}</name>'
        f"<pv_name>{escape(pv)}</pv_name>{geometry(x, y, w, 20)}"
        f"<border_alarm_sensitive>true</border_alarm_sensitive>"
        f"<tooltip>$(pv_name)\n$(pv_value)</tooltip></widget>"
    )


def severity_led(pv: str, tooltip: str, x: int, y: int) -> str:
    states = "".join(
        f"<state><value>{i}</value><label>{name}</label>"
        f"<color>{colour(name, rgb)}</color></state>"
        for i, (name, rgb) in enumerate(SEVERITY_COLOURS)
    )
    return (
        f'<widget type="multi_state_led" version="2.0.0"><name>{escape(pv)}</name>'
        f"<pv_name>{escape(pv)}.SEVR</pv_name>{geometry(x, y, 20, 20)}"
        f"<states>{states}</states>"
        f"<tooltip>{escape(tooltip)}: $(pv_name) $(pv_value)</tooltip></widget>"
    )


def bool_led(pv: str, tooltip: str, x: int, y: int) -> str:
    return (
        f'<widget type="led" version="2.0.0"><name>{escape(pv)}</name>'
        f"<pv_name>{escape(pv)}</pv_name>{geometry(x, y, 20, 20)}"
        f"<tooltip>{escape(tooltip)}: $(pv_name) $(pv_value)</tooltip></widget>"
    )


def led(spec: str, tooltip: str, x: int, y: int) -> str:
    kind, pv = spec.split(":", 1)
    if kind == "SEVR":
        return severity_led(pv, tooltip, x, y)
    return bool_led(pv, tooltip, x, y)


def open_button(text: str, file: str, x: int, y: int, w: int, tooltip: str) -> str:
    return (
        f'<widget type="action_button" version="3.0.0"><name>{escape(text)}</name>'
        f'<actions><action type="open_display"><file>{escape(file)}</file>'
        f"<target>tab</target><description>{escape(tooltip)}</description>"
        f"</action></actions><text>{escape(text)}</text>{geometry(x, y, w, 20)}"
        f"<tooltip>{escape(tooltip)}</tooltip></widget>"
    )


def group(title: str, x: int, y: int, w: int, h: int, body: list[str]) -> str:
    return (
        f'<widget type="group" version="3.0.0"><name>{escape(title)}</name>'
        f"{geometry(x, y, w, h)}{''.join(body)}</widget>"
    )


def ioc_panel(iocs: list[Ioc], opis: str, x: int, y: int) -> tuple[str, int, int]:
    # columns: label | IOC button | CPU | uptime | autosave | kind
    w = 910
    body = [
        label("IOC", 250, 0, 200, bold=True),
        label("CPU", 460, 0, 40, bold=True),
        label("Uptime", 500, 0, 150, bold=True),
        label("Save", 660, 0, 40, bold=True),
        label("Runs as", 710, 0, 180, bold=True),
    ]
    row_y = ROW
    for ioc in iocs:
        body.append(label(ioc.label, 0, row_y, 245))
        if ioc.service and ioc.kind == "ibek":
            body.append(
                open_button(
                    ioc.name,
                    f"{opis}/{ioc.service}/index.bob",
                    250,
                    row_y,
                    200,
                    f"Screens published by {ioc.service}",
                )
            )
        else:
            body.append(label(ioc.name, 255, row_y, 195))
        if ioc.load_pv:
            body.append(severity_led(ioc.load_pv, "CPU load", 470, row_y))
            body.append(text_update(f"{ioc.name}:UPTIME", 500, row_y, 150))
        if ioc.autosave:
            body.append(
                severity_led(f"{ioc.autosave}SR_status", "Autosave", 670, row_y)
            )
        body.append(label(ioc.kind, 710, row_y, 190))
        row_y += ROW
    h = row_y + GAP
    return group("IOCs", x, y, w, h, body), w, h


def device_panel(
    title: str, devices: list[Device], opis: str, x: int, y: int
) -> tuple[str, int, int]:
    w = 560
    body = []
    row_y = 0
    for d in devices:
        body.append(label(d.label, 0, row_y, 300))
        lx = 305
        for tip, spec in d.leds:
            body.append(led(spec, tip, lx, row_y))
            lx += 25
        if d.text_pv:
            body.append(text_update(d.text_pv, lx, row_y, 100))
        body.append(
            open_button(
                d.service,
                f"{opis}/{d.service}/index.bob",
                420,
                row_y,
                130,
                f"Screens published by {d.service}",
            )
        )
        row_y += ROW
    h = row_y + GAP + 25
    return group(title, x, y, w, h, body), w, h


def render_bob(conf: dict, iocs: list[Ioc], devices: list[Device]) -> str:
    opis = str(conf.get("opis_root", DEFAULT_OPIS_ROOT))
    widgets = [label(conf["title"], 10, 5, 600, bold=True)]
    panel, w, h = ioc_panel(iocs, opis, 10, TITLE_H)
    widgets.append(panel)

    x = 10 + w + 20
    y = TITLE_H
    width = x
    for title in DEVICE_GROUPS:
        members = [d for d in devices if d.group == title]
        if not members:
            continue
        panel, pw, ph = device_panel(title, members, opis, x, y)
        widgets.append(panel)
        y += ph + GAP
        width = x + pw + 10
    height = max(TITLE_H + h, y) + 20

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<display version="2.0.0">\n'
        f"  <name>{escape(conf['title'])}</name>\n"
        f"  <width>{width}</width>\n  <height>{height}</height>\n"
        + "\n".join(f"  {w}" for w in widgets)
        + "\n</display>\n"
    )


def hardware_status(services_repo: Path) -> tuple[Path, int, int]:
    """Write the screen for ``services_repo``; return its path and the
    numbers of IOCs and devices on it."""
    screen_dir = services_repo / SCREEN_DIR
    config = screen_dir / CONFIG_NAME
    if not config.is_file():
        raise FileNotFoundError(f"{config} not found")
    conf = _load_yaml(config) or {}
    for key in ("title", "beamline_services"):
        if key not in conf:
            raise ValueError(f"{config}: missing '{key}'")
    iocs, devices = read_services(services_repo / "services", conf)
    out = screen_dir / OUTPUT_NAME
    out.write_text(render_bob(conf, iocs, devices), encoding="utf-8")
    return out, len(iocs), len(devices)
