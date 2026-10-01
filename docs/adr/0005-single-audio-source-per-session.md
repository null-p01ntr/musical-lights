# 005. One audio source per session, with Take control

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Several browsers may have the page open; mixing their levels would make lights flicker.

## Decision

The first client to send levels becomes `Engine.source`; levels from others are ignored. A
client can claim the session explicitly ("Take control"), which restarts the watchdog clock.
If the source disconnects the watchdog decides whether the session ends.

## Consequences

- Levels handling must keep the `client is self.source` guard.
