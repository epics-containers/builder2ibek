# New module folder — check, then ask the user

A new module folder in `ibek-support-dls/` or `ibek-support/` is a decision for
the user, never a default. Many modules are deliberately absent: deprecated,
replaced, moved, or served by a runtime pattern instead. This rule covers
creating a folder only; adding an entity model to a folder that already exists
needs no question.

Before creating `ibek-support-dls/<module>/` or `ibek-support/<module>/`:

1. **Check for a ruling.** Read
   [module-special-cases.md](module-special-cases.md). If it has a section on
   the module (won't convert, replaced, held, moved, forbidden, or a fixed
   location or casing), follow it and don't create the folder.
2. **Check whether it already exists**, under any casing or `_dls` suffix:
   ```bash
   ls -d ibek-support-dls/*/ ibek-support/*/ | grep -i '<module>'
   gh api repos/epics-containers/ibek-runtime-streamdevice/contents --jq '.[].name' | grep -i '<module>'
   gh api repos/epics-containers/ibek-runtime-support/contents --jq '.[].name' | grep -i '<module>'
   ```
   A module lives in exactly one of the two support repos (see CLAUDE.md). If
   an `ibek-runtime-streamdevice` or `ibek-runtime-support` pattern exists, it
   is preferred over a build-time module: the IOC vendors it with
   `ibek pattern add` (see
   [ibek-pattern-vendoring](../ibek-pattern-vendoring/SKILL.md)).
3. **Check for a public upstream** (GitHub `epics-modules`, `areaDetector`,
   `epics-motor`, `paulscherrerinstitute`, `DiamondLightSource`, …). If one
   exists, the folder belongs in `ibek-support/`, built from that upstream, not
   in `ibek-support-dls/`. epics-containers prefers public upstreams to DLS
   forks; `ibek-support-dls/` is for modules with no public source.
4. **Stop and ask the user** with AskUserQuestion. The question names the
   module, the IOC or IOCs that need it, and the findings of steps 1–3, and
   offers these options:
   - create it in `ibek-support/`, built from the public upstream
   - create it in `ibek-support-dls/`
   - use the runtime pattern
   - don't convert it (the IOC is flagged for the user)

   Create the folder only as the user's answer says. A subagent, or any agent
   that can't ask, stops before creating the folder and reports the module,
   the IOCs and its findings to its caller, which asks the user.
