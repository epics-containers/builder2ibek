---
name: skills-edit
description: Create, edit, or review the Claude skills in this repo. Use when asked to add a skill, update a skill's instructions, review skill quality, or refactor shared skill docs.
argument-hint: [<skill-name>]
---

# Skills Editor

This repo's `.claude/skills/` directory contains the domain knowledge that
drives all AI-assisted IOC conversion. Editing skills well is as important as
editing code.

---

## Skill system layout

```
.claude/skills/
  <skill-name>/SKILL.md      # One dir per user-invocable skill
  shared/<topic>.md          # Reference docs shared across skills
```

Skills are discovered automatically — no registration needed. Each `SKILL.md`
must have YAML frontmatter.

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

When adding a concept, ask: does it already exist in one of the above? If so,
link to it rather than repeating it.

### Self-contained subagents
Subagents work best when their briefing is self-contained. Prefer including
key rules inline in the subagent prompt over chains of "see shared/foo.md"
indirection. Exception: long reference docs (like ibek-concepts) that subagents
should read in full — pass those as "read this file first" instructions.

### Subagents read skills directly
When an orchestrator skill spawns a subagent to run another skill, it passes
the skill file path for the subagent to read:
```
Read /workspaces/builder2ibek/.claude/skills/support-create/SKILL.md
and follow its instructions for module: <name>
```
This keeps the orchestrator lean — it doesn't need to inline the full skill.

### EPICS_ROOT isolation for parallel subagents
Any skill that runs `ibek` commands must create an isolated EPICS_ROOT:
```bash
export EPICS_ROOT=$(mktemp -d)
./update-schema
```
This prevents parallel subagents from clobbering each other's schema state.

### Batch size
Beamline-scale skills (beamline-convert, beamline-check) run up to **10
subagents in parallel** per batch. Wait for each batch before launching the
next.

---

## When to use shared/ vs inline

| Content | Where |
|---|---|
| Reused across 3+ skills | `shared/<topic>.md` |
| Used in one skill only | Inline in that skill's SKILL.md |
| Conceptual reference (long) | `shared/` + "read this file first" in skill |
| Brief reminder of a rule | Inline with a link to the authoritative source |

---

## Quality checklist for a skill

- [ ] Frontmatter `description` clearly states when to trigger it
- [ ] No concept duplicated from another skill — links instead
- [ ] Subagent skills include EPICS_ROOT isolation instructions
- [ ] Shared docs referenced by path (relative from skills root)
- [ ] `disable-model-invocation: true` set if skill spawns subagents
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
