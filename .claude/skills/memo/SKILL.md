---
name: memo
description: Save current task state to auto-memory, then promote reusable lessons to skills and trim memory.
---

# Memo

Save a snapshot of current work to persistent memory, then clean up.

## Step 1 — Save current state

Write a concise summary of in-progress or recently completed work to
`/root/.claude/projects/-workspaces-builder2ibek/memory/MEMORY.md`. Include:

- What was done (beamline/IOC name, module, etc.)
- Current status (completed, blocked, in-progress)
- Key decisions or outcomes

Do not duplicate information already in skills or CLAUDE.md.

## Step 2 — Promote to skills

Review the memory file for items that represent **reusable patterns or
lessons** — things that would help future conversions. For each such item:

1. Identify which skill file it belongs in (support-yaml-rules.md,
   builder-py-analysis.md, ioc-convert, beamline-convert, etc.)
2. Add it to the appropriate skill
3. Remove it from memory (it now lives in the skill)

Examples of promotable items:
- A new "foot-gun" pattern (e.g. subagents reverting shared files)
- A module that needs special handling (e.g. ethercat → TODO stub)
- A type-mapping rule discovered during conversion

## Step 3 — Trim memory

Remove from memory anything that is:
- Already captured in skills or CLAUDE.md
- Too specific to a single IOC to be useful in future sessions
- Stale or superseded by later work

Keep memory concise — ideally under 30 lines.
