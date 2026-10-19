---
description: Walk a new user through eng-tools ONBOARDING.md Part 1 and check this machine - Python 3.11+ with PyYAML, kicad-cli, both repos side by side, this plugin - reporting what is missing.
disable-model-invocation: true
---

# /eng-onboard

Walk the user through Part 1 of `ONBOARDING.md` in eng-tools and check this machine. You check
and report; the user does the installing, each step with their own yes.

**On Windows** there is no `python3`: python.org installs `python.exe` and the `py` launcher,
and the Store's `python3` is a stub that opens the Store. Wherever this command runs `python3`,
run `py -3` instead (the Bash tool there is Git Bash). Python's UTF-8 mode must be on
(`PYTHONUTF8=1`; `/eng-onboard` checks it) (ES-069).

## Find the tools

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.py" --where`. It prints the
eng-standards and eng-tools this machine resolves to. They come only from the plugin's
`engstd_root` option as saved in the user settings file; `--where` also prints any
`ENGSTD_ROOT` / `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` in the environment, marked "(ignored)" -
report both values to the user and use the saved one. Do not use the env-override mode of
`--where`. `<eng-tools>` below is the `eng-tools:` line. If it prints
`NOT FOUND`, show the user that line and continue with the next paragraph: never guess a path.

If `--where` finds nothing, that is the first finding: ask the user where they cloned (or
will clone) the two repos, side by side in one folder - called `<STD>` in the docs - and
once the clones exist, have them set the plugin's `engstd_root` option (`/plugin`, or `/config`)
to the eng-standards clone - that is their step, not yours - and re-run `--where`.

## 1. Read Part 1 with the user

Read `<eng-tools>/ONBOARDING.md` and walk through "Part 1" step by step, quoting each step.
Do not restate it from memory; if the file is not there, say which path you checked.

## 2. Check, one line each, PASS / FAIL / MISSING with the evidence

| check | how | PASS when |
|---|---|---|
| Python | `python3 -c "import sys; print(sys.version)"` | 3.11 or newer |
| PyYAML | `python3 -c "import yaml; print(yaml.__version__)"` | imports |
| KiCad CLI | `kicad-cli version` (on macOS also `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli version`) | prints a version, 8 or newer |
| git | `git --version` | prints a version |
| Windows: Git for Windows | `git --version` prints `windows`; `bash --version` (the Bash tool runs it) | both print a version |
| Windows: UTF-8 mode | `py -3 -c "import sys; print(sys.flags.utf8_mode)"` | prints `1` (set once with `setx PYTHONUTF8 1`, then restart Claude) |
| Windows: hook Python | `py -3 --version`, else a python.org, conda or scoop install | one is found: the guard's launcher looks there, never on PATH |
| eng-tools clone | `git -C "<STD>/eng-tools" rev-parse HEAD` | a commit |
| eng-standards clone | `git -C "<STD>/eng-standards" rev-parse HEAD` | a commit |
| side by side | both are direct children of the same `<STD>` | same parent |
| guard hook | `<STD>/eng-standards/hooks/guard_auditor.py` exists | exists |
| this plugin | `claude plugin list` lists `engstd` enabled (read-only) | listed |
| guard location | `--where` prints `eng-standards:` (from the saved `engstd_root` option) and no "(ignored)" line | found |
| skills | the five skills are available in this session (`ecad-design-document`, `mechanical-engineering-standard`, `mcad-env`, `git-concurrent-sessions`, `refresh-program-board`) - from this plugin or `~/.claude/skills/` | all five |

Run the Windows rows only on Windows; elsewhere they are n/a. If `python3` is older than 3.11, look for another interpreter before calling it FAIL (`python3.11`,
`python3.12`, the mcad env from the `mcad-env` skill) and name what you found.

A check you could not run is MISSING, not PASS. Name the path or command for each.

## 3. Report

The table, then "what is missing", each with the exact command from Part 1 the user would
run to fix it. **Offer; do not run.** Installs, clones, `pip install`, plugin installs and
edits to `~/.claude` are the user's to approve, one at a time. Then point to Part 2 of
`ONBOARDING.md` (the prompt to run inside their project repo) and to `/eng-init`.

## Ask first, every time

Ask the user, and wait for a yes in their own message, before any of: `git commit`, `git push`,
creating or changing a remote, installing anything (packages, envs, plugins), editing any file
outside the repo this command is about, installing or changing hooks or settings, deleting
anything, running anything fetched from the web. Approval is scoped to the one thing approved:
a yes to the dry run is not a yes to the real run, and a yes to commit is not a yes to push.
