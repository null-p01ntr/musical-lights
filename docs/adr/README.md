# Architecture Decision Records

Decisions that shape this project and that a future contributor (human or agent) could
not recover from the code alone. One file per decision, numbered, never deleted.

- Create one with the `/adr "<title>"` skill, or copy `0000-template.md`.
- Status: `proposed` → `accepted` → optionally `superseded by NNNN` / `deprecated`.
- Don't edit an accepted ADR's decision. Write a new ADR that supersedes it and update
  the old one's status line only.
- Write one when a change touches something listed here, or when you pick between real
  alternatives that the next person might want to revisit.

| # | Title | Status |
|---|---|---|
| [0001](0001-browser-side-audio-analysis.md) | Analyse audio in the browser, not the server | accepted |
| [0002](0002-helper-toggle-instead-of-automations.md) | A HA toggle helper instead of managing automations | accepted |
| [0003](0003-paced-output-and-session-restore.md) | Rate-capped output and snapshot/restore of lights | accepted |
| [0004](0004-https-self-signed-no-auth.md) | Self-signed HTTPS and no authentication | accepted |
| [0005](0005-single-audio-source-per-session.md) | One audio source per session, with Take control | accepted |
| [0006](0006-no-offline-service-worker.md) | PWA installable but no offline caching | accepted |
| [0007](0007-single-file-backend-no-frontend-build.md) | Single-file backend, no frontend build step | accepted |
| [0008](0008-agentic-development-structure.md) | Claude-controlled development structure | accepted |
| [0009](0009-repository-layout.md) | Repository layout: src/, docs/, base + prod compose | accepted |
| [0010](0010-agent-harness-guardrails.md) | Agent harness guardrails: git pull only, secrets protected | accepted |
