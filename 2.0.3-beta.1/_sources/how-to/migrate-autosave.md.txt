# Migrating saved autosave values to an ibek IOC

`builder2ibek migrate-autosave` converts the **saved values** from a legacy DLS
IOC's autosave files into the two `.sav` files an ibek Generic IOC restores at
startup.

This is the companion to [](autosave.md): that command generates the `.req`
files (which PVs to save); this command migrates the last-saved **data** so the
new IOC boots with the old IOC's setpoints already in place.

## Background

A legacy DLS IOC writes its autosave data to per-set files named
`<IOC>_0.sav`, `<IOC>_1.sav`, `<IOC>_2.sav`, each line carrying an explicit
field name:

```
# autosave R5.3	Automatically generated - DO NOT MODIFY
BL19I-VA-GAUGE-05:ILKSETSP:NOWRITE.VAL 1
<END>
```

An ibek IOC instead restores from `autosave_positions.sav` (pass 0) and
`autosave_settings.sav` (pass 1), using the bare record name:

```
BL19I-VA-GAUGE-05:ILKSETSP:NOWRITE 1
```

`migrate-autosave` reformats the legacy set into these two files following the
DLS pass convention — **set 0 → positions, sets 1+ → settings** — dropping a
trailing `.VAL` from each line.

## Why this is a safe, naive conversion

The conversion needs **no knowledge of the new IOC's PV set** (its `.req`
files). At restore, autosave applies whatever `PV value` lines it finds and
silently ignores any PV the IOC does not have, then re-saves its own set on the
first save pass. So:

- PVs the new IOC no longer carries are restored harmlessly and drop out of the
  `.sav` files by themselves on the first save.
- PVs the new IOC has but the legacy file lacks simply keep their default value.

## Finding the legacy set

Only the **current** save of each set is used: files matching `<stem>_<N>.sav`
exactly. Autosave's rolling backups are deliberately excluded because they carry
extra characters after `.sav`:

| File | Used? |
|---|---|
| `BL19I-VA-IOC-01_0.sav` | yes — the live save of set 0 |
| `BL19I-VA-IOC-01_0.sav0`, `...savB` | no — round-robin sequence backups |
| `BL19I-VA-IOC-01_0.sav_260611-091551` | no — dated restart archive |
| `...SBAD...` | no — flagged-bad save |

If the input folder holds more than one stem the command stops and asks you to
pick one with `--from`.

## Running the command

```bash
uv run builder2ibek migrate-autosave [INPUT_FOLDER] [OUTPUT_FOLDER] [OPTIONS]
```

Both folders default to the current directory, so run it inside the folder
holding the legacy `.sav` files for the simplest folder-in / folder-out case.

### Arguments

| Argument | Description |
|---|---|
| `INPUT_FOLDER` | Folder holding the legacy `<IOC>_N.sav` set (default: cwd) |
| `OUTPUT_FOLDER` | Folder to write `autosave_{positions,settings}.sav` into (default: cwd) |

### Options

| Option | Description |
|---|---|
| `--from`, `-f STEM` | IOC stem (e.g. `BL19I-VA-IOC-01`) selecting which set to use; only needed when the input folder holds more than one stem |
| `--backup` / `--no-backup` | Copy an existing destination to `<file>.bak` before overwriting (default: backup) |
| `--clean` / `--no-clean` | Remove round-robin sibling files (`.sav0`/`.savB`/…) of each written target so the IOC cannot restore a stale one — dated archives are kept (default: clean) |
| `--dry-run` | Report what would happen but write nothing |

### Output files

- `autosave_positions.sav` — from legacy set `0`
- `autosave_settings.sav` — from legacy sets `1` and above (de-duplicated, last value wins)

## Example

Preview the conversion without writing anything:

```bash
uv run builder2ibek migrate-autosave \
    /srv/software/bl19i/epics/autosave/BL19I-VA-IOC-01 \
    ./BL19I-VA-IOC-01/autosave \
    --dry-run
```

When the plan looks right, drop `--dry-run` to write the two `.sav` files.

## Where to place the output

Write the two `.sav` files into the IOC instance's autosave location — the same
directory the running ibek IOC mounts and restores from at boot (for an RTEMS
hybrid IOC this is the NFS autosave mount; see the rtems-proxy autosave
notes). Commit them alongside the IOC instance if you want the migrated values
under version control.
