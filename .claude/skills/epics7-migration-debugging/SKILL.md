---
name: epics7-migration-debugging
description: >-
  Diagnose runtime errors that appear on a containerised EPICS 7 IOC but not on
  the traditional EPICS 3.14 IOC it was converted from. Use when an error is
  suspected to be a base-version behaviour change rather than a conversion bug,
  or when you need to reproduce IOC startup behaviour in-container.
---

# Debugging EPICS 3.14 -> 7 behaviour changes

Converted IOCs in this project run base 7 where the originals ran R3.14.12.7.
A large class of "new" errors are **pre-existing template defects that base 7
reports and 3.14 silently tolerated**. Confirm which class you are in before
patching anything.

Two recurring shapes:

- **New checks.** Base 3.16+ rewrote link handling; `dbCanSetLink()` now rejects
  link-type mismatches that 3.14 accepted without comment.
- **Errors that stopped being swallowed.** Soft device supports that used to
  `return 2` unconditionally now return the real status. Anything downstream that
  depended on a failed read *looking* successful changes behaviour.

The second shape is the dangerous one — it fails silently with wrong values
rather than logging.

## Confirm against real 3.14 source, don't guess

`/epics/epics-base` is a **full clone with tags back to 3.14**, not a shallow
checkout. Use it rather than reasoning about what 3.14 "probably" did:

```bash
git -C /epics/epics-base show R3.14.12.7:src/db/dbAccess.c        # 3.14 paths differ
git -C /epics/epics-base log --oneline --follow -- modules/database/src/std/dev/devAiSoft.c
git -C /epics/epics-base tag --contains <sha> | grep -E '^R[0-9]' | sort -V | head
```

`--follow` matters: base was reorganised (`Move all under modules/database`), so
plain `git log` on a current path stops at the move. `tag --contains` gives the
first release carrying a change, which is what you report to users.

## Reproduce in-container with the real IOC binary

The built IOC is at `/epics/ioc/bin/linux-x86_64/ioc` with `/epics/ioc/dbd/ioc.dbd`.
Drive it with a hand-written st.cmd instead of guessing from logs:

```
dbLoadDatabase("/epics/ioc/dbd/ioc.dbd")
ioc_registerRecordDeviceDriver(pdbbase)
dbLoadRecords("/path/to/extract.db", "device=TEST,temp=:T1,...")
iocInit
dbgf "TEST:T1.HIGH"
exit
```

Run it with CA confined to loopback and a non-default port so it cannot disturb
anything real:

```bash
EPICS_CA_SERVER_PORT=45064 EPICS_CAS_INTF_ADDR_LIST=127.0.0.1 \
EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO \
timeout 60 /epics/ioc/bin/linux-x86_64/ioc st.cmd
```

**Extract the records under test into a reduced db.** Loading a full DLS template
usually crashes the test IOC in device support (`devEtherIP ... Failed to all
drvEtherIP_init()` then a core dump) because no hardware port exists. Replace
hardware records with soft equivalents; keep the soft records byte-identical.

## Split iocInit to find *when* a value is destroyed

`iocInit` is `iocBuild` + `iocRun`, and both are iocsh commands. Stepping through
them separately is the single most useful trick here, because it straddles the
boundary that most startup bugs hinge on:

- `iocBuild` ends with `initialProcess()` — all `PINI` processing happens here.
- `iocRun` calls `scanRun()` then `dbCaRun()` — **CA links only start working now.**

```
iocBuild
dbgf "..."      # PINI done, CA links still dead
iocRun
epicsThreadSleep 2
dbgf "..."      # CP monitors have now fired
```

A value that is correct after `iocBuild` and wrong after `iocRun` was destroyed by
a `CP` monitor firing on connection. A value already wrong after `iocBuild` was
destroyed during `PINI`. Autosave restores before either (pass 0 at
`initHookAfterInitDevSup`, pass 1 at `initHookAfterInitDatabase`), so an autosaved
value is always present by `initialProcess` — if it is missing there, something
overwrote it, autosave is not at fault.

Note `CP` on a link forces a **CA** link even to a local PV (`dbLink.c:118`), in
both 3.14 and 7. So any record whose `INP` carries `CP` cannot read during
`iocBuild`.

## Foot-gun: `patch_lines` appends when the regexp misses

`ibek-support` `patch_lines` is `ansible.builtin.lineinfile`, which **appends
`line` to the file when `regexp` matches nothing** — silently corrupting a db or
Makefile rather than failing. Two rules:

1. Verify the regexp matches, and matches only what you intend, before shipping it.
2. Write the regexp so it **also matches your replacement**, or a re-run appends a
   duplicate. Match on `^\s*field\(SIOL,` rather than the full original text.

`comment_out` is riskier still for `.vdb` files, since VisualDCT re-emits them
during the build and may not preserve comments. Prefer `patch_lines` there.

Patch the `.vdb` source, not the generated `.template` — `dlsPLCApp/Db/*.vdb` is
flattened by VisualDCT at container build time.
