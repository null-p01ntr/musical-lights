# 004. Self-signed HTTPS and no authentication

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Browsers only expose the microphone in a secure context, and this is a home-LAN tool.

## Decision

`src/entrypoint.sh` generates a self-signed certificate into `/data/certs` on first start and the
app serves HTTPS only. There is no login; the HA token is write-only through the API.

## Alternatives considered

- **Real CA certificates / reverse proxy**: more setup than the target user wants; still
  possible in front of the container.
- **Add auth**: out of scope for a trusted LAN.

## Consequences

- Never expose the port to the internet; keep this warning in the README.
- Never return the token from any endpoint.
