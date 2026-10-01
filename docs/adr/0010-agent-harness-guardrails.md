# 10. Agent harness guardrails

- Status: accepted
- Date: 2026-10-01

## Context

The project is managed with AI coding agents. The checkout holds a live Home Assistant
token in `.env`, and the app can actuate real lights. An agent once printed the resolved
compose config, leaking the token into a transcript. Permission rules alone don't stop
that: they match command prefixes, and the Bash tool can read files the Read tool denies.

## Decision

- Enforce policy in PreToolUse hooks (`.claude/hooks/guard.py`, stdlib Python, fail
  closed), with permission rules as a second layer.
- Git: agents may run only `git pull`. `gh` is blocked. Committing, pushing and history
  changes are done by the human.
- Secrets: agents cannot read or write `.env*` (except `.env.example`), `data/`, `*.key`,
  `*.pem`, and cannot dump the environment or use `docker inspect/exec`. Resolved compose
  config is allowed only as `config -q`.
- The harness itself (`.claude/settings*.json`, `.claude/hooks/`) requires user
  confirmation to change.
- Tests run from a project venv (`.venv/`) via the Stop hook.

## Alternatives considered

- **Permission rules only**: prefix matching is bypassed by option reordering, chaining
  and other tools.
- **Shell hooks using jq**: fail open when jq is missing.

## Consequences

- Agents must ask the user to run blocked commands (`! git commit ...`).
- The guard is a heuristic, not a sandbox: it cannot stop every indirect route (for
  example code that reads a file). Keep secrets out of the checkout where possible and
  review diffs before pushing.
- It scans the whole command text, so a command that merely mentions a blocked word (in a
  heredoc, say) is refused; write such text with the file tools instead.
- Changing the policy means editing the hook and this ADR (supersede it).
