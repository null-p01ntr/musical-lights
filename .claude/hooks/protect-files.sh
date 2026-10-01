#!/bin/sh
# PreToolUse: refuse edits to secrets/runtime state. Exit 2 = block, stderr goes to Claude.
f=$(jq -r '.tool_input.file_path // empty')
case "$f" in
  */.env|*/.env.local|*/data/*|*/.git/*)
    echo "Blocked: $f is secret or runtime state (.env, data/, .git/). Edit .env.example instead." >&2
    exit 2 ;;
esac
exit 0
