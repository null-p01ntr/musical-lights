#!/bin/sh
# PostToolUse: fast syntax check of any edited .py file. Silent on success.
f=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
case "$f" in
  *.py) python3 -m py_compile "$f" 2>&1 >/dev/null || { echo "Syntax error in $f (see above)" >&2; exit 2; } ;;
esac
exit 0
