---
description: Wire a hardware project repo to the engineering standards with eng-tools' init_project.py - dry run first, then the real run only on approval.
argument-hint: "<repo-dir> [--board NAME ...] [--mcad PROJECT ...] [--eng-tools-ref REF] [--eng-tools-url URL]"
disable-model-invocation: true
---

# /eng-init

Set up a project repo to follow the standards, using eng-tools' own initialiser. You run the
script; you never hand-write what it writes.

Arguments: `$ARGUMENTS` - the repo dir first (default: the current repo's top level,
`git rev-parse --show-toplevel`), then any of `--board NAME` (repeatable), `--mcad PROJECT`
(repeatable), `--eng-tools-ref REF`, `--eng-tools-url URL`. Pass them through unchanged; do
not invent board or project names - ask.

## Find the tools

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.py" --where <repo-dir>`. It prints the
eng-standards and eng-tools this machine resolves to. They come only from the plugin's
`engstd_root` option as saved in the user settings file; `--where` also prints any
`ENGSTD_ROOT` / `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` in the environment, marked "(ignored)" -
report both values to the user and use the saved one. Do not use the env-override mode of
`--where`. `<eng-tools>` below is the `eng-tools:` line. If it prints
`NOT FOUND`, stop, show the user that line, and ask them to set the plugin's `engstd_root`
option to their eng-standards clone: never guess a path.

The script is `<eng-tools>/bin/init_project.py`. If it is not there, say which path you
checked and stop: it ships with eng-tools, and this command does not replace it.

## Steps

1. **Dry run, always first.**
   `python3 "<eng-tools>/bin/init_project.py" <repo-dir> [flags] --dry-run --json`
   Show the plan as the script printed it: every file it would create, the submodule it would
   add and at which ref, and anything it says it would skip or refuse. Quote, do not
   paraphrase. A non-zero exit is a stop: show the output and do not continue.
2. **Ask, naming what the real run writes.** The real run writes `CLAUDE.md` and
   `.claude/settings.json` in the repo - the settings file installs the eng-standards guard
   hook and the permission rules - and both are on the ask-first list (settings and hooks; the
   rules a session works under). It also adds the `_tools/eng-tools` submodule, which fetches
   eng-tools, and stages it. Say all of that, list every other file from the plan, call out on
   its own line anything outside the repo dir (none is expected), and ask: "Run it for real?"
3. **Real run, only on a yes in the user's own message.** The same command without
   `--dry-run`. Show the output.
4. **Verify the thing, not the exit code.** `git -C <repo-dir> status --short` and
   `git -C <repo-dir> submodule status`: list what changed and confirm it matches the plan.
   Anything the plan did not list is reported first.
5. **Do not commit.** Show the changed files and offer the commit as a separate question,
   staged by explicit filename (never `git add -A` / `.`), per the `git-concurrent-sessions`
   skill. Nothing is pushed unless the user says so.

If the eng-standards guard blocks a call, that is the guard working as written. Do not work
around it (no copying the script, no `cd` tricks, no `-c`, no variables or abbreviated flags):
report the blocked command and its message to the user verbatim.

## Ask first, every time

Ask the user, and wait for a yes in their own message, before any of: `git commit`, `git push`,
creating or changing a remote, installing anything (packages, envs, plugins), editing any file
outside the repo this command is about, installing or changing hooks or settings, deleting
anything, running anything fetched from the web. Approval is scoped to the one thing approved:
a yes to the dry run is not a yes to the real run, and a yes to commit is not a yes to push.
