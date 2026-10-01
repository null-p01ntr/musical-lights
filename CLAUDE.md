# CLAUDE.md

MusicalLights drives Home Assistant (HA) lights from a browser microphone. The browser does all audio work (Web Audio FFT → bass/mid/treble levels 0..1) and sends levels over a WebSocket to a small aiohttp server, which holds the HA token and paces commands to HA over its own WebSocket. User-facing behavior, config variables and the HTTP/WS API: @README.md

## Commands

| Task | Command |
|---|---|
| Setup once | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (`.venv/` is git-ignored; the Stop hook uses it) |
| All tests | `.venv/bin/python -m unittest discover -s src/tests -v` |
| One test | `.venv/bin/python -m unittest discover -s src/tests -k <test_name>` |
| Tests in image | `docker compose run --rm --no-deps --entrypoint python musical-lights -m unittest -v tests.test_app` |
| Validate compose | `docker compose -f compose.yaml -f compose.prod.yaml config -q` |
| Run | `docker compose -f compose.yaml -f compose.prod.yaml up -d` (add `--build` to build locally) |

No lint, format, build or migration step exists. CI (`.github/workflows/deploy.yml`) runs the tests, then publishes a multi-arch image to ghcr.io on main/tags.

- `compose.yaml` is shared base config and publishes no port; `compose.prod.yaml` adds the image tag (`ML_TAG`), restart policy and host port (`ML_PORT`, default 8445; container listens on 8443). Alternatively set `COMPOSE_FILE` in `.env`.
- `src/entrypoint.sh` generates a self-signed cert into `/data/certs` because browsers require HTTPS for mic access. `python src/app.py` directly needs `TLS_CERT`/`TLS_KEY` and `DATA_DIR` (default `/data`).

## Architecture

Backend is one file, `src/app.py`; frontend is plain static files in `src/static/` (no bundler, no framework). Data flow: browser mic → `live.js` FFT → `/ws` → `Engine` (20 Hz paced loop) → `HAClient` → HA WebSocket.

- `Settings`: persists to `$DATA_DIR/settings.json`. `HA_URL`/`HA_TOKEN`/`HA_HELPER` env vars **override** and lock those fields in the UI (`ENV_HA`). `ML_LIGHTS` seeds the light list on first run only. The token is write-only through the API.
- `HAClient`: one persistent HA WebSocket that reconnects forever, plus REST lookups; `reload()` after settings changes. Reports helper state and reconnects via `on_helper` / `on_connect`, which `Engine` wires up.
- `Engine`: session state machine, 20 Hz output loop (`TICK_S`), pushes state to browsers at 10 Hz. Lifecycle: helper on → wait 1 s → snapshot lights → drive → restore on/off and brightness → helper off. Ends on toggle, no-audio watchdog, helper turned off in HA, or shutdown; a leftover helper is turned off on reconnect after a crash. Only `Engine.source` feeds levels; other browsers use "Take control".
- Output pacing is the core constraint: per-light rate cap, deadband, keepalive (`KEEPALIVE_S`), switch hysteresis plus minimum hold. Dimmable vs on/off is decided by `kind` (`kind_from_state`, `ONOFF_DOMAINS`). Colour is never changed.
- `make_app()` wires routes and static files; `errors_mw` turns `BadRequest` into JSON errors. It takes injectable `settings`/`ha`/`engine`, which tests rely on.
- Frontend: `live.js` (mic, FFT, spectrum, WS client), `settings.js`, `sw.js`. Brand art source: `docs/brand/`; served icons: `src/static/icons/`.

## Rules

- Before changing session lifecycle, output pacing, security or the PWA: read the relevant ADR. Index: @docs/adr/README.md (pacing/restore: @docs/adr/0003-paced-output-and-session-restore.md; harness guardrails: @docs/adr/0010-agent-harness-guardrails.md).
- Never edit an accepted ADR's decision; supersede it with `/adr`.
- Tests assert against `FakeHA`'s recorded service calls (`src/tests/test_app.py`), not mocked internals. New behavior gets a test.
- Run `/verify` before calling work done. After touching `Engine`, `HAClient` or API routes, run the `ha-safety-reviewer` subagent. Use `test-writer` for new tests, `/add-light-domain` for new HA domains.

## Don'ts

- Don't add caching to `sw.js`: a cached shell with no backend is worse than a clear failure (ADR 0006).
- Don't change light colour, add a frontend build step, or split `app.py` without an ADR.
- Don't send light commands outside the pacing path, or leave a session-end path without restore.
- Don't print, copy or commit secret values (HA token, certs); never return the token from an API.
- Don't read or edit `.env*` (except `.env.example`), `data/`, `*.key`, `*.pem`. Hooks enforce this.
- Only `git pull` is allowed; `gh`, `docker inspect/exec`, inline `-c` shells, env dumps and `docker compose config` without `-q` are blocked. If you need one, ask the user to run it with `!`.
- Don't edit `.claude/settings*.json` or `.claude/hooks/` without user confirmation. Personal overrides go in `.claude/settings.local.json` (git-ignored).
