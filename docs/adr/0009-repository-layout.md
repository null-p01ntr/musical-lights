# 9. Repository layout

- Status: accepted
- Date: 2026-10-01

## Context

Source, deployment config and docs were mixed at the repo root, and one compose file
mixed shared config with production concerns.

## Decision

- Application code, its static frontend, tests and entrypoint live in `src/`; docs
  (including ADRs and brand art) in `docs/`.
- `compose.yaml` is the shared base; `compose.prod.yaml` overrides the image tag, restart
  policy and published port. `.env` selects them via `COMPOSE_FILE`.
- Secrets stay out of git: `.env`, `*.key`, `*.pem` and `data/` are ignored, and a
  gitleaks pre-commit hook scans commits.
- CI is `.github/workflows/deploy.yml`: test, then build and push the multi-arch image to
  ghcr.io. It does not deploy to a host; hosts pull the image.

## Consequences

- Paths in docs, hooks and skills refer to `src/...`; the Dockerfile copies `src/` to `/app`.
- Plain `docker compose up` (base only) builds locally and publishes no port.
