# 002. A HA toggle helper instead of managing automations

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Other Home Assistant automations will fight the app for the same lights while music plays.

## Decision

The user creates one `input_boolean` helper. The app turns it on for the duration of a
session and off afterwards; users guard their own automations on it. The app never creates
or edits automations. Turning the helper off in HA ends the session.

## Alternatives considered

- **Create/disable automations from the app**: invasive, hard to undo cleanly, needs
  broad HA permissions.

## Consequences

- Session start waits 1 s after turning the helper on so reacting automations settle
  before lights are snapshotted.
- On reconnect after a crash a leftover helper is turned off.
