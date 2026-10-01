#!/bin/sh
# Stop: run the suite when code changed since HEAD; if it fails, keep Claude working.
# Skips when stop_hook_active is set so a failing run can't loop forever.
input=$(cat)
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
git status --porcelain -- src 2>/dev/null | grep -q . || exit 0
python3 -c "import aiohttp" 2>/dev/null || { echo "run-tests hook skipped: aiohttp not installed (pip install -r requirements.txt, ideally in a venv)" >&2; exit 0; }
out=$(python3 -m unittest discover -s src/tests 2>&1) && exit 0
printf 'Tests failed. Fix before finishing:\n%s\n' "$(printf '%s' "$out" | tail -40)" >&2
exit 2
