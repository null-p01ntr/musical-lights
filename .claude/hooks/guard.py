#!/usr/bin/env python3
"""PreToolUse guard. Usage: guard.py files|bash  (hook JSON on stdin).

Blocks with exit 2 (stderr goes to Claude). Fails CLOSED: any unexpected error blocks.
Pure stdlib, no jq. Policy:
  files: no Read/Edit/Write/Grep of secret files (.env*, data/, keys); asks before
         touching the harness itself (.claude/settings*.json, .claude/hooks/).
  bash:  only `git pull` is allowed from git; no `gh`; no .env / data/ access; no env
         dumps; `docker compose config` only with -q (it prints resolved secrets).
"""
import json
import os
import re
import shlex
import sys

SECRET_PATH = re.compile(
    r"(^|/)(\.env(?!\.example$)(\.[^/]*)?|data(/.*)?|[^/]*\.(key|pem))$")
HARNESS_PATH = re.compile(r"(^|/)\.claude/(settings[^/]*\.json|hooks/.*)$")


def block(msg):
    print(f"Blocked by .claude/hooks/guard.py: {msg}", file=sys.stderr)
    sys.exit(2)


def ask(msg):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": msg}}))
    sys.exit(0)


def check_files(inp):
    for key in ("file_path", "path", "notebook_path"):
        p = inp.get(key)
        if not p:
            continue
        rel = os.path.relpath(os.path.realpath(p), os.path.realpath(os.getcwd()))
        if SECRET_PATH.search(rel) or SECRET_PATH.search(p):
            block(f"{p} is secret or runtime state (.env, data/, keys). "
                  "Use .env.example for documentation.")
        if HARNESS_PATH.search(rel) and key == "file_path":
            ask(f"{p} is part of the agent harness (permissions/hooks); confirm this edit.")


GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def git_subcommand(words):
    """words[0] == 'git'. Return the subcommand, skipping global options."""
    i = 1
    while i < len(words):
        w = words[i]
        if w in GIT_VALUE_OPTS:
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w
    return None


def check_bash(inp):
    cmd = inp.get("command", "")
    # Quoted shell-in-shell / eval can hide anything; refuse them outright.
    if re.search(r"\b(eval|source)\b|\b(ba|z|da)?sh\s+-c\b|\bpython3?\s+-c\b", cmd):
        block("shell/python -c and eval are not allowed (they bypass command checks).")
    if re.search(r"(?<![\w.-])\.env(?!\.example\b)(?![\w-])", cmd) or \
       re.search(r"(^|[\s/=\"'])data/", cmd):
        block("this command touches .env or data/ (secrets / runtime state).")
    if re.search(r"(^|[;&|\s])(printenv|env|export\s+-p|declare\s+-x)(\s|$)", cmd):
        block("dumping the environment can leak secrets.")
    lex = shlex.shlex(cmd.replace("`", ";"), posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        block("could not parse command safely.")
    segments, cur = [], []
    for t in tokens:
        if t and set(t) <= set(";&|()<>\n"):
            segments.append(cur)
            cur = []
        else:
            cur.append(t)
    segments.append(cur)
    for words in segments:
        while words and (re.fullmatch(r"\w+=.*", words[0]) or words[0] in ("sudo", "command", "exec", "time", "xargs", "nohup")):
            words.pop(0)
        if not words:
            continue
        prog = os.path.basename(words[0])
        if prog == "gh":
            block("gh is not allowed.")
        if prog == "git":
            sub = git_subcommand(words)
            if sub != "pull":
                block(f"only `git pull` is allowed (got git {sub}). The user runs other git commands.")
        if prog == "docker" and "compose" in words and "config" in words:
            if not any(w in ("-q", "--quiet") for w in words):
                block("`docker compose config` prints resolved secrets; use `config -q`.")
        if prog in ("docker", "docker-compose") and any(w in ("inspect", "exec") for w in words[:3]):
            block("docker inspect/exec can expose container environment (secrets).")


def main():
    try:
        mode = sys.argv[1]
        data = json.load(sys.stdin)
        inp = data.get("tool_input") or {}
        {"files": check_files, "bash": check_bash}[mode](inp)
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block(f"guard error ({e!r}); refusing.")


main()
