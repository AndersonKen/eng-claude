---
description: Run the pinned eng-tools checkers on this project's boards and parts and report every row as PASS, FAIL, MISSING, WARN or n/a.
argument-hint: "[board dir or mcad project ...]"
disable-model-invocation: true
---

# /eng-audit

Run the project's own pinned checkers - the copy at `_tools/eng-tools` in this repo, which is
the version this project is held to - and report what they say. You report; you never decide
a row yourself, and you never fix anything in this command.

Arguments: `$ARGUMENTS` - board directories and/or mcad project directories. With none,
find them: board dirs are folders holding a `KiCAD/` (or a `.kicad_pro`) with a `docs/`
beside it; mcad projects are folders holding a `register.yaml`. List what you found and the
paths you searched before running anything.

If `_tools/eng-tools` is missing or empty (`git submodule status` shows `-`), say so and stop:
every row is MISSING and nothing was checked. Do not fall back to another eng-tools copy -
the pin is the point.

## Run, per target (read-only: no `--write-report`, no `--tests`)

| target | command | exit codes |
|---|---|---|
| board | `python3 _tools/eng-tools/ecad-tools/bin/check_standard.py "<board dir>"` | 0 every row ok · 1 a FAIL row · 2 rows printed, none FAIL, some MISSING (or usage, with no rows) |
| board | `python3 _tools/eng-tools/ecad-tools/bin/check_sch.py "<board dir>" --all` | 0 no FAIL · 1 a FAIL · 2 usage, or a project/sheet/table that does not read |
| mcad project | `<mcad python> _tools/eng-tools/mcad-tools/check_register.py "<project>"` | 0 no ERROR · 1 an ERROR |

`--all` makes `check_sch.py` list its PASS findings, so they can be counted. `<mcad python>` is
the CadQuery env from the `mcad-env` skill, never a bare `python3` that lacks CadQuery. If no
such env is available here, the mcad rows are MISSING ("not checked: no mcad env"), not
skipped silently.

Record each command's exit code beside its output. **An exit code is not a result:**
`check_standard.py` exits 2 when it printed every row and some are MISSING - report those rows.
Only when a checker printed no rows at all (usage error, unreadable input) is every row it
would have produced MISSING; then show its message.

## Report

One table per target, every row or finding the checker printed, in its order:

| state | row | detail |
|---|---|---|

Use the checker's own state, mapped onto these words and nothing else:

| the checker printed | report as |
|---|---|
| `ok`, `PASS` | **PASS** |
| `FAIL`, `ERROR` | **FAIL** |
| `WARN`, `WARNING` | **WARN** - listed, never counted as PASS |
| `n/a` | **n/a**, with the checker's reason |
| `MISSING`, `INFO` (cannot decide), "not checked", or a checker that would not run | **MISSING** |

Then one summary line per target: `<n> PASS, <n> FAIL, <n> MISSING, <n> WARN, <n> n/a`.
**MISSING is never counted, worded or coloured as passing**, and a target is "clean" only with
0 FAIL and 0 MISSING.

If the eng-standards guard blocks a call, that is the guard working as written. Do not work
around it (no copying the script, no `cd` tricks, no `-c`, no variables or abbreviated flags):
report the blocked command and its message to the user verbatim.

## Ask first, every time

Ask the user, and wait for a yes in their own message, before any of: `git commit`, `git push`,
creating or changing a remote, installing anything (packages, envs, plugins), editing any file
outside the repo this command is about, installing or changing hooks or settings, deleting
anything, running anything fetched from the web. Approval is scoped to the one thing approved:
a yes to the dry run is not a yes to the real run, and a yes to commit is not a yes to push.
