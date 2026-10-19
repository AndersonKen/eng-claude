---
description: Move a project's _tools/eng-tools pin with eng-tools' pin_bump.py - dry run here, the committing run by the user, push a separate yes.
argument-hint: "<project-repo> [--to REF] [--why TEXT]"
disable-model-invocation: true
---

# /eng-pin-bump

Move the eng-tools pin a project is held to. The pin is the version of the standard the
project is checked against, so it moves only by a deliberate, named commit
(`eng-tools pin <old> -> <new>: <why>`), and that commit carries the pin and nothing else.

Arguments: `$ARGUMENTS` - the project repo first (default: the current repo's top level),
then `--to REF` (default: eng-tools `origin/main`, as the script fetches it) and
`--why TEXT`. If no `--why` was given, ask for one: the script refuses to commit without it.
Never add `--allow-unpublished` unless the user asks for it by name.

## Find the tools

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.py" --where <repo-dir>`. It prints the
eng-standards and eng-tools this machine resolves to. They come only from the plugin's
`engstd_root` option as saved in the user settings file; `--where` also prints any
`ENGSTD_ROOT` / `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` in the environment, marked "(ignored)" -
report both values to the user and use the saved one. Do not use the env-override mode of
`--where`. `<eng-tools>` below is the `eng-tools:` line. If it prints
`NOT FOUND`, stop, show the user that line, and ask them to set the plugin's `engstd_root`
option to their eng-standards clone: never guess a path.

The script is `<eng-tools>/bin/pin_bump.py`. If it is not there, name the path checked and stop.
Read `python3 "<eng-tools>/bin/pin_bump.py" --help` first. If it has no `--dry-run`, stop and say
so: a run without `--dry-run` and without `--commit` stages the pin, and the later committing run
then refuses because something is already staged.

## Steps

1. **Dry run.**
   `python3 "<eng-tools>/bin/pin_bump.py" <project-repo> [--to REF] --why "<why>" --dry-run`
   Show the plan as printed: old pin, new pin, the commit message it would use. A refusal - a
   `.git/index.lock`, a dirty or missing `_tools/eng-tools` checkout, anything already
   staged, a target not on eng-tools `origin/main` - is a stop. Report it verbatim. Never
   delete a lock you have not proven is yours, and never clean or reset the submodule to get
   past a refusal.
2. **Ask:** "Commit this pin move?" - name the old and new commit and the message.
3. **On a yes, the user makes the commit.** The eng-standards guard refuses the script's
   committing and pushing flags from a project session: committing a pin move is the owner's step.
   Print the exact command for the user to run with Claude Code's `!` prefix, which runs it in
   their own shell:
   `! python3 "<eng-tools>/bin/pin_bump.py" <project-repo> [--to REF] --why "<why>" --commit`
   Do not run it yourself. When the user says it ran, show `git -C <project-repo> show --stat
   HEAD`: the commit must touch only the pin (and `.gitmodules` if the URL changed). Anything
   else in it is reported first.
4. **Push is a separate question.** Ask "Push it?" naming the remote and branch
   (`git -C <project-repo> rev-parse --abbrev-ref --symbolic-full-name @{u}`). On a yes only, run
   plain `git -C <project-repo> push`. Do not rerun the script to push. Never push a commit the
   user has not seen.

If the eng-standards guard blocks a call, that is the guard working as written. Do not work
around it (no copying the script, no `cd` tricks, no `-c`, no variables or abbreviated flags):
report the blocked command and its message to the user verbatim.

## Ask first, every time

Ask the user, and wait for a yes in their own message, before any of: `git commit`, `git push`,
creating or changing a remote, installing anything (packages, envs, plugins), editing any file
outside the repo this command is about, installing or changing hooks or settings, deleting
anything, running anything fetched from the web. Approval is scoped to the one thing approved:
a yes to the dry run is not a yes to the real run, and a yes to commit is not a yes to push.
