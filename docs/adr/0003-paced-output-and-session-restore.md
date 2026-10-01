# 003. Rate-capped output and snapshot/restore of lights

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Wi-Fi and cloud bulbs drop commands when flooded; relays wear out if toggled rapidly; users
expect their lights back the way they were.

## Decision

The engine ticks at 20 Hz but sends per-light commands only within a max updates/s cap and a
brightness deadband, with a keepalive resend. On/off devices use a threshold with
hysteresis and a minimum hold. Every light is snapshotted at session start and restored
(on/off and brightness, never colour) at the end, including on page close, watchdog
timeout, or helper-off.

## Alternatives considered

- **Send every frame**: floods devices.
- **Skip restore**: leaves rooms in a random state.

## Consequences

- Any change to output code must preserve the pacing limits and the restore path on every
  session-end route. `Engine.target_for` is pure and unit-tested.
- A watchdog (default 6 s without audio) ends sessions whose source disappeared.
