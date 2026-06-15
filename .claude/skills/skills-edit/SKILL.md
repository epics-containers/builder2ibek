---
name: skills-edit
description: Create, edit, or review the Claude skills and slash commands in this repo. Use when asked to add a skill or command, update their instructions, review quality, or refactor shared docs.
argument-hint: [<skill-or-command-name>]
---

# Skills and Commands Editor

This repo's `.claude/` directory holds the domain knowledge that drives all
AI-assisted IOC conversion. It splits into two parts:

- **Skills** (`.claude/skills/<name>/SKILL.md`) — reference knowledge that
  Claude auto-loads when a task's context matches the skill description.
  Currently: `ibek-concepts`, `ibek-support-ansible`, `skills-edit`.
- **Commands** (`.claude/commands/<name>.md`) — explicit user workflows
  invoked via `/<name>` with arguments. Currently: `ioc-convert`,
  `ioc-convert-raw`, `ioc-check`, `ioc-inspect`, `beamline-convert`,
  `beamline-check`, `beamline-reconvert`, `support-create`, `support-fix`,
  `support-inspect`, `memo`.

Editing either well is as important as editing code.

---

## Layout

```
.claude/
  commands/<name>.md         # User-invoked slash commands — take $1, $2 args
  skills/
    <skill-name>/SKILL.md    # Auto-invoked reference knowledge (no args)
    shared/<topic>.md        # Reference docs shared across skills/commands
```

Both kinds are discovered automatically — no registration needed. Each file
must have YAML frontmatter.

---

## Choosing skill vs command

Use a **command** when:
- The file takes positional arguments (IOC name, beamline prefix, paths)
- The user invokes it explicitly as a workflow (`/ioc-convert foo.xml`)
- It orchestrates subagents or runs a procedure

Use a **skill** when:
- It's reference material (concepts, rule tables, build system docs)
- It has no arguments and should be auto-loaded when the topic comes up
- Its description is a trigger condition for Claude's skill picker

---

## Frontmatter format

```yaml
---
name: skill-name                  # matches directory name
description: One sentence.        # shown in skill picker — be precise about trigger conditions
argument-hint: <arg1> [<arg2>]    # shown as usage hint (optional)
disable-model-invocation: true    # add for skills that use subagents (prevents double-invocation)
---
```

---

## Design principles

### Authoritative sources — avoid duplication
Each concept should live in exactly one place:
- `ibek-concepts/SKILL.md` — ibek entity model rules (Jinja2, databases.args, type:id/object, auto_*)
- `shared/support-yaml-rules.md` — brief reminders + links to ibek-concepts
- `shared/error-categorization.md` — generate2 error patterns and known recurring issues
- `shared/services-repo-resolution.md` — how to find/clone the services repo
- `shared/find-*.md` — filesystem search patterns (module path, boot script, IOC XMLs)
- `shared/builder-py-analysis.md` — how to read a builder.py systematically
- `shared/vxworks-to-rtems-differences.md` — VxWorks vs RTEMS API differences
- `shared/module-rename-map.md` — old DLS → epics-containers module/verb renames
  for raw-IOC conversion (`/ioc-convert-raw`)

When adding a concept, ask: does it already exist in one of the above? If so,
link to it rather than repeating it.

### Self-contained subagents
Subagents work best when their briefing is self-contained. Prefer including
key rules inline in the subagent prompt over chains of "see shared/foo.md"
indirection. Exception: long reference docs (like ibek-concepts) that subagents
should read in full — pass those as "read this file first" instructions.

### Subagents read command files directly
When an orchestrator command spawns a subagent to run another command, it
passes the command file path for the subagent to read:
```
Read /workspaces/builder2ibek/.claude/commands/support-create.md
and follow its instructions for module: <name>
```
This keeps the orchestrator lean — it doesn't need to inline the full command.

### EPICS_ROOT isolation for parallel subagents
Any command that runs `ibek` must create an isolated EPICS_ROOT:
```bash
export EPICS_ROOT=$(mktemp -d)
./update-schema
```
This prevents parallel subagents from clobbering each other's schema state.

### Batch size
Beamline-scale commands (beamline-convert, beamline-check) run up to **10
subagents in parallel** per batch. Wait for each batch before launching the
next.

---

## When to use shared/ vs inline

| Content | Where |
|---|---|
| Reused across 3+ skills or commands | `skills/shared/<topic>.md` |
| Used in one file only | Inline in that skill/command |
| Conceptual reference (long) | `skills/shared/` + "read this file first" in file |
| Brief reminder of a rule | Inline with a link to the authoritative source |

Relative path from a command file (`.claude/commands/foo.md`) into shared docs
is `../skills/shared/<topic>.md`. From a skill file
(`.claude/skills/<name>/SKILL.md`) it's `../shared/<topic>.md`.

---

## Quality checklist

Skills:
- [ ] Frontmatter `description` clearly states when to auto-trigger it
- [ ] No arguments — skills are reference, not workflows
- [ ] No concept duplicated elsewhere — links instead

Commands:
- [ ] Frontmatter `description` + `argument-hint` shown in the `/` picker
- [ ] Uses positional placeholders (`$1`, `$2`) matching the argument-hint
- [ ] Subagent-spawning commands include EPICS_ROOT isolation instructions
- [ ] Shared docs referenced by `../skills/shared/<topic>.md`
- [ ] Steps are numbered and ordered — Claude follows them sequentially

---

## MEMORY.md hygiene

`~/.claude/projects/-workspaces-builder2ibek/memory/MEMORY.md` is loaded into
every context (including subagents). Keep it minimal:
- Personal/session preferences only (e.g. "memo" = save task state to memory)
- Do NOT store things that belong in CLAUDE.md or skills
- Do NOT store volatile state (test counts, in-progress conversion status)
- Lessons from conversions → distil into `error-categorization.md` or the
  relevant skill, then remove from memory
