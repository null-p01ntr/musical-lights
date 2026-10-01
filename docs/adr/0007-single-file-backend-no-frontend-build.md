# 007. Single-file backend, no frontend build step

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Small project deployed as one container, maintained largely by agents and one person.

## Decision

The backend is one module (`src/app.py`, aiohttp only). The frontend is plain HTML/CSS/JS in
`src/static/` with no bundler or framework. Tests use stdlib `unittest` with a fake HA.

## Consequences

- Revisit by ADR if `src/app.py` outgrows comfortable review size; splitting is allowed but
  must keep `make_app()` injectable for tests.
