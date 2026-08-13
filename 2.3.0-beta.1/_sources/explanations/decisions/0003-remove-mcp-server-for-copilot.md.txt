# 3. Remove MCP server for GitHub Copilot

## Status

Accepted

## Context

We built an MCP server (`mcp_server.py`) exposing five tools — `find_module_path`,
`find_boot_script`, `find_ioc_xmls`, `support_inspect`, and `ioc_inspect` — so that
GitHub Copilot users without a Claude subscription could query the DLS filesystem and
analyze IOC/module structure from VS Code agent mode.

The goal was to let colleagues use builder2ibek's capabilities without needing Claude
Code.

## Decision

We are removing the MCP server and all associated configuration because the tools
provide **data retrieval without the intelligence needed to act on it**.

The actual conversion workflow requires significant LLM reasoning that cannot be encoded
as deterministic code:

- **Interpreting** builder.py classes and deciding which to model vs skip.
- **Deciding** parameter types by cross-referencing db templates, boot scripts, and XML
  usage patterns (e.g. inferring `type: float` from EPICS record field usage).
- **Generating** correct ibek support YAMLs with the right `type: id` vs `type: object`
  decisions, `pre_init`/`post_init` commands, and database macro mappings.
- **Writing** converters that handle edge cases (stripping `name`, renaming attributes,
  deduplication).
- **Diagnosing** validation errors and determining the correct fix.

The MCP tools are essentially "hands without a brain" — they give Copilot raw data but
Copilot lacks the domain-specific reasoning that our Claude Code skills and subagents
provide.

### Alternatives considered

1. **MCP tools that shell out to `claude` CLI** — would delegate the reasoning to Claude,
   but requires every user to have a Claude subscription, defeating the original goal.

2. **Smarter mid-level tools** — tools that go beyond data retrieval (e.g. generating
   draft support YAMLs). However, the reasoning needed is too nuanced for deterministic
   code and would produce unreliable output that gives false confidence.

3. **Keep tools as investigation aids** — the tools are useful for exploration, but
   Copilot users can achieve the same by reading files directly. The MCP layer adds
   maintenance burden without sufficient value.

## Consequences

- Colleagues without Claude Code cannot use AI-assisted conversion workflows. Full
  IOC conversion requires Claude Code with the `/ioc-convert` skill.
- The `.github/copilot-instructions.md` is retained as it provides useful domain context
  for Copilot users doing manual work, independent of MCP tools.
- Reduced maintenance burden — no need to keep MCP tools in sync with evolving
  skill/subagent architecture.
