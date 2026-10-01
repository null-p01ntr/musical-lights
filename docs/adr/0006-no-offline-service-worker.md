# 006. PWA installable but no offline caching

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Chrome requires a service worker with a fetch handler for install. The app is only useful
with a live backend.

## Decision

`src/static/sw.js` exists for installability only and caches nothing.

## Consequences

- Do not add caching: a stale cached shell with no backend is worse than a clear
  "unreachable" failure.
