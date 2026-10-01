# 8. Claude-controlled development structure

- Status: accepted
- Date: 2026-10-01

## Context

The project is developed mainly through Claude Code. Agents start cold each session, so
conventions and rationale must live in the repo, and routine guardrails should be enforced
mechanically rather than remembered.

## Decision

- `CLAUDE.md` is the entry point: commands, architecture, and the workflow rules.
- `docs/adr/` records decisions; agents consult it before changing anything it covers and
  add one when making a significant choice.
- `.claude/settings.json` holds shared permissions and hooks (committed). Personal overrides
  go in `.claude/settings.local.json` (git-ignored).
- Hooks: syntax-check Python after edits; block edits to `.env` and `data/`; run the tests
  when Claude finishes a turn that changed code under `src/`.
- Skills (`.claude/skills/`): `adr`, `verify`, `add-light-domain`. Subagent
  (`.claude/agents/`): `ha-safety-reviewer`.

## Alternatives considered

- **Only CLAUDE.md**: no enforcement, and rationale gets mixed with how-to.

## Consequences

- Hook scripts must stay fast and quiet on success; a failing hook output is fed back to
  the agent.
- New durable conventions go in CLAUDE.md or an ADR, not in chat.
