---
name: beamline-gui
description: DLS beamline EDM screen layout and conventions — use when locating, reading, or editing `*.edl` files for hardware-status / IOC-status synoptics, debugging wrong-target buttons (PC / Terminal / Start-Stop), or making sense of EDM positional layout.
---

# Beamline GUI (EDM Screens)

DLS beamline GUIs are EDM `.edl` files. This skill covers where they live and
how the common synoptic screens are wired.

---

## Where the screens live

Pattern (same for every beamline):

```
/dls_sw/{work,prod}/R<EPICS-VER>/ioc/BLxxI/BL/
  BLxxIApp/opi/edl/*.edl     # SOURCE — edit these
  data/*.edl                 # deployed copy — overwritten by build; do not edit
```

`*.edl~` are EDM editor backups — ignore.

`/dls_sw/work/` is the unreleased tree (edit here); `/dls_sw/prod/` is the
released equivalent (read-only).

**EPICS version varies per beamline.** `R3.14.12.7` is currently the most
common, but older beamlines may still live under `R3.14.11`, `R3.14.12.3`,
`R3.14.8.2`, etc., and newer / RTEMS-based ones under `R7.0.7`. Don't hard-code
the version — discover it:

```bash
ls -d /dls_sw/{work,prod}/R*/ioc/BLxxI/BL 2>/dev/null
```

Pick the most recent / actively-modified tree (check mtimes on the `edl/`
directory if there are several).

---

## Key screens

| File | Purpose |
|---|---|
| `BLxxI-hardware-status.edl` | Top-level synoptic for the beamline |
| `BLxxI-ioc-status-embed.edl` | Per-IOC rows; embedded in hardware-status via `activePipClass` |

The hardware-status screen embeds the ioc-status-embed via `displayFileName`.

---

## How a row is laid out

EDM is positional. A row of buttons shares a single `y` coordinate; the row's
human-readable name is a `(Static Text)` object at the same y on the left.
Buttons sit at increasing `x`. **Object order in the file does not follow
visual order — match by coordinates, not file position.**

Typical row (left to right):

| Element | Class | Real wiring lives in |
|---|---|---|
| Row label | `activeXTextClass` | `value { "Merlin 01 IOC" }` — cosmetic |
| IOC button | `relatedDisplayClass` | `displayFileName: ioc_stats_soft`, `symbols: ioc=$(dom)-XX-IOC-NN` |
| Traffic light | `activeSymbolClass` | `controlPvs: <IOC>:LOAD.SEVR` |
| Terminal | `shellCmdClass` | `command: gnome-terminal -x console <IOC>` |
| Start/Stop | `relatedDisplayClass` | `procServControl.edl`, `symbols: procServ=<IOC>` |
| PC | `shellCmdClass` | `command: dls-remote-desktop.sh ... <hostname>` |
| Save/Restore icon | `relatedDisplayClass` | `save_restoreStatus_more`, `symbols: P=<IOC>` |

`$(dom)` is the beamline domain macro (e.g. `BL20I`), substituted at runtime.

---

## Finding the code behind a visible button

1. Grep the row's static-text label (the name shown on screen):
   ```bash
   grep -n '"Merlin 02 IOC"' BLxxI-ioc-status-embed.edl
   ```
2. Read around the hit to find the row's `y` coordinate.
3. Grep `buttonLabel` (or the action class — `shellCmdClass`, `relatedDisplayClass`)
   and look for objects with the same y — those are the buttons in that row.

Don't trust `buttonLabel` text alone: the visible label and the actual target
in `command` / `symbols` can disagree. That mismatch is the "wrong PC" bug class.

---

## Wiring/label mismatch (the wrong-target bug)

Each PC / Terminal / Start-Stop button has a `command` string (or `symbols`
substitution) naming the real target. The visible label is decorative. When
a button "opens the wrong thing", the fix is in `command` or `symbols`, not
in the label or the static text next to it.

Two buttons that target swapped hosts get fixed by swapping the `command`
strings — coordinates, colours, and labels stay put.

---

## Editing rules

- Edit `BLxxIApp/opi/edl/<file>.edl` — never `data/<file>.edl` (deployed
  output, overwritten on build).
- Never touch `*.edl~` (EDM autosave).
- When swapping wiring between rows, preserve x/y/colours/labels; change only
  the `command` / `symbols` lines.
