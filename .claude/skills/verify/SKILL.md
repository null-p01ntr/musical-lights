---
name: verify
description: Run the full verification pass (syntax, unit/e2e tests, config sanity) before declaring a change done or committing. Use after any change to src/, Dockerfile or compose files.
---

# Verify

Run, in order, and report each result faithfully (never claim a pass you didn't see):

1. `.venv/bin/python -m py_compile src/app.py src/tests/test_app.py` (create the venv first if missing, see CLAUDE.md)
2. `.venv/bin/python -m unittest discover -s src/tests -v`
3. If `Dockerfile`, `compose*.yaml` or `src/entrypoint.sh` changed: `docker compose config -q`,
   `docker compose -f compose.yaml -f compose.prod.yaml config -q` and `sh -n src/entrypoint.sh`.
4. If `src/static/` changed: check that every file referenced by `src/static/index.html`,
   `src/static/settings.html` and `src/static/manifest.json` exists. UI behaviour can't be fully
   verified without a browser and a mic, so say so rather than implying it was tested.
5. If the change touches output pacing, session start/stop or restore: confirm a test
   covers the changed path (see ADR 0003); add one if not.
6. If the change contradicts an ADR in `docs/adr/`, stop and use the `adr` skill.
