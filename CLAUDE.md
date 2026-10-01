# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MusicalLights drives Home Assistant (HA) lights from a browser microphone. The browser does all audio work (Web Audio FFT → bass/mid/treble levels 0..1) and sends levels over a WebSocket to a small aiohttp server, which holds the HA token and paces commands to HA over its own WebSocket. See `README.md` for user-facing behavior, config variables and the HTTP/WS API.

## Repo layout

`src/` (app, `static/`, `tests/`, `entrypoint.sh`), `docs/` (ADRs in `docs/adr/`, brand art), `Dockerfile` and `compose.yaml` / `compose.prod.yaml` at the root, `.env.example` (committed; `.env` is git-ignored), `.pre-commit-config.yaml` (gitleaks secret scan; run `pre-commit install`), and the CI workflow `.github/workflows/deploy.yml`.

## Commands

- Tests (stdlib `unittest`, only dependency is `aiohttp`; no lint/build step):
  - all: `python -m unittest discover -s src/tests -v`
  - one: `python -m unittest discover -s src/tests -k <test_name>`
  - in the image (`src/` is copied to `/app`): `docker compose run --rm --no-deps --entrypoint python musical-lights -m unittest -v tests.test_app`
- Run: `docker compose -f compose.yaml -f compose.prod.yaml up -d` (or set `COMPOSE_FILE` in `.env`; add `--build` to build locally instead of pulling). `compose.yaml` is shared base config and publishes no port; `compose.prod.yaml` adds the image tag (`ML_TAG`), restart policy and the host port (`ML_PORT`, default 8445; container listens on 8443). `src/entrypoint.sh` generates a self-signed cert into `/data/certs` because browsers require HTTPS for mic access. Running `python src/app.py` directly needs `TLS_CERT`/`TLS_KEY` and `DATA_DIR` (defaults to `/data`).
- CI (`.github/workflows/deploy.yml`) runs the tests, then publishes a multi-arch image to ghcr.io on main/tags.

## Architecture

Backend is a single file, `src/app.py`; frontend is plain static files in `src/static/` (no bundler, no framework).

- `Settings`: persists to `$DATA_DIR/settings.json`. `HA_URL`/`HA_TOKEN`/`HA_HELPER` env vars **override** and lock those fields in the UI (`ENV_HA`). `ML_LIGHTS` seeds the light list on first run only. The token is write-only through the API.
- `HAClient`: one persistent HA WebSocket that reconnects forever, plus REST lookups; `reload()` after settings changes. It reports the helper's state and reconnects via the `on_helper` / `on_connect` callbacks, which `Engine` wires up.
- `Engine`: the session state machine and the 20 Hz output loop (`TICK_S`); pushes state to browsers at 10 Hz. Session lifecycle: turn helper on → wait 1 s → snapshot lights → drive → restore on/off and brightness → turn helper off. A session ends on the toggle, the no-audio watchdog, the helper being turned off in HA, or shutdown. A leftover helper is turned off on reconnect after a crash. Only one browser (`Engine.source`) feeds levels per session; others use "Take control".
- Output pacing is the core design constraint: per-light rate cap, deadband, keepalive resend (`KEEPALIVE_S`), and switch hysteresis plus minimum hold, so real Wi-Fi/cloud bulbs and relays aren't flooded. Dimmable lights vs on/off devices are distinguished by `kind` (`kind_from_state`, `ONOFF_DOMAINS`). Colour is never changed.
- `make_app()` wires the aiohttp routes (`/api/*`, `/ws`) and static files; `errors_mw` turns `BadRequest` into JSON errors. It takes injectable `settings`/`ha`/`engine`, which the tests rely on.
- Frontend: `live.js` (main page: mic, FFT, band levels, spectrum, WS client), `settings.js` (settings page), `sw.js` (a deliberately no-op service worker, present only to satisfy PWA install criteria; do not add caching, since a cached shell with no backend is worse than a clear failure). Icon source art is in `docs/brand/`; the served icons are in `src/static/icons/`.

## Testing notes

`src/tests/test_app.py` uses a `FakeHA` that speaks the same WebSocket/REST shapes as HA and records every service call; assert against those calls rather than mocking internals. The Dockerfile copies all of `src/` (tests included) into the image so tests can run in the container.

## Working in this repo (agentic workflow)

- **ADRs** in `docs/adr/` record why things are the way they are (index in `docs/adr/README.md`). Read the relevant ones before changing session lifecycle, output pacing, security, or the PWA/service worker. Never edit an accepted ADR's decision; supersede it with the `/adr` skill.
- **Skills** (`.claude/skills/`): `/adr` (write or supersede an ADR), `/verify` (full check before calling work done), `/add-light-domain` (support a new HA entity domain). Subagent `ha-safety-reviewer` checks diffs against the ADR invariants; use it after touching `Engine`, `HAClient` or API routes.
- **Hooks** (`.claude/settings.json`, scripts in `.claude/hooks/`, need `jq`): edits to `.env`, `data/` and `.git/` are blocked (edit `.env.example` instead); edited `.py` files are syntax-checked; on finishing a turn that changed anything under `src/`, the test suite runs and failures send you back to fix them.
- Put personal permission/hook overrides in `.claude/settings.local.json` (git-ignored), not `settings.json`.
