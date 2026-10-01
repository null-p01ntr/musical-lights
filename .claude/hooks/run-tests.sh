#!/bin/sh
# Stop: run the suite when code under src/ changed; if it fails, keep Claude working.
# Skips when stop_hook_active is set so a failing run can't loop forever.
# Uses the project venv (.venv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt).
cat | grep -q '"stop_hook_active": *true' && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
git status --porcelain -- src 2>/dev/null | grep -q . || exit 0
PY=.venv/bin/python
[ -x "$PY" ] || { echo "run-tests hook skipped: no .venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2; exit 0; }
out=$("$PY" -m unittest discover -s src/tests 2>&1) && exit 0
printf 'Tests failed. Fix before finishing:\n%s\n' "$(printf '%s' "$out" | tail -40)" >&2
exit 2
