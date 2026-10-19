# Changelog

## 0.2.0 — 2026-10-19

Windows (ES-069):

- `hooks/hooks.json` is shell form: `/bin/sh "${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.sh"`,
  run by `sh -c` on macOS and Linux and by Git Bash on Windows. The exec form (`command`
  `/bin/sh` with `args`) is spawned without a shell, and on Windows `/bin/sh` is no executable,
  so there every call was a hook error. `PowerShell` joins the PreToolUse matcher.
- The launcher, on Windows, finds Python only in folders the system names: the py launcher,
  then python.org installs (newest), then conda bases and scoop; never PATH, never the Store
  alias. `PY_PYTHON` and the py launcher's other variables are unset.
- The shim, on Windows, runs Git for Windows' `git.exe` from a known folder (CreateProcess
  finds a bare `git` on the parent's PATH, whatever the child's env says), reads the settings
  file from the profile folder rather than Git Bash's `HOME`, and compares submodule paths
  without case.
- Commands say to run `py -3` where they say `python3`; `/eng-onboard` checks Git for Windows,
  UTF-8 mode and a Python the launcher finds.
- Tests: platform-only tests are collected only where they can run; the Windows launcher
  branch is tested on any OS through a copy with its folders pinned. 7 new mutants.

## 0.1.1 — 2026-10-02

- mechanical-engineering-standard: section 4 (Environment) removed at the owner's request; the `mcad-env` skill covers environments. Security floor renumbered to 4.

## 0.1.0 — 2026-10-02

First version (ES-060), revised across three review rounds:

- The eng-standards guard now runs the commands' scripts (ES-059); `/eng-pin-bump` hands the committing run to the user, since the guard refuses `--commit` from a session.
- Guard hook scoped to eng project sessions (`CLAUDE_PROJECT_DIR` with a `_tools/eng-tools`
  submodule, not a `<STD>` repo); silent elsewhere. The guard is found from `ENGSTD_ROOT`, the
  `engstd_root` plugin option, or the project's local submodule clone only; `eng.toml` and the
  cwd walk are gone. ConfigChange hooked for settings sources only.
- Skills re-copied from the current sources; every change declared in `tests/skill_map.json`.
- `/eng-pin-bump`: `--dry-run`, one `--commit` run, plain `git push`. `/eng-audit`: rows, not exit
  codes; `check_sch.py --all`; WARN and n/a states. `/eng-init` names the settings files it writes.

Second review round:

- The guard location comes only from the `engstd_root` option saved in user settings; an
  `ENGSTD_ROOT` or `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` from the environment is ignored and
  reported. The submodule-URL fallback is gone.
- Scope is decided from the eng-tools gitlink recorded at HEAD or in the index, not the working
  tree; a missing or bogus `CLAUDE_PROJECT_DIR` warns.
- The skill line map and its generator moved out of git; `SOURCES.md` lists the source skills. Skills re-synced with the current sources.

Third review round:

- Scope holds if any of four signals does: gitlink at HEAD, gitlink in the index, working-tree
  `.gitmodules`, `_tools/eng-tools/.git`. A `.git` that git rejects warns.
- The hook runs through `scripts/engstd_guard.sh` (fixed `PATH`, `python3 -I`); `git` runs on
  the fixed `PATH`.
- The ecad skill's repo inventory of scripts is dropped as a project fact; skills re-synced.
- The skills are maintained in this repo from now on: final migration from the owner's synced
  skills on 2026-10-02 (`SOURCES.md`); no regeneration at release.

Fourth review round:

- The one-time migration check is retired (verified at dbdea0e); its map and generator left
  the repo.
- The launcher warns NOT GUARDED when there is no `python3` and the session looks like an eng
  project; silent elsewhere.
- A `.gitmodules` entry counts only as `_tools/eng-tools`, or as a `.../_tools/eng-tools` path
  with an `eng-tools` / `eng-tools.git` URL.

As first built:

- Five skills, copied from the owner's skill folders with names scrubbed: `ecad-design-document`,
  `mechanical-engineering-standard`, `mcad-env`, `git-concurrent-sessions`, `refresh-program-board`.
  Paths to the retired vendored tool copies were updated to the one pinned `_tools/eng-tools` (ES-021).
- Guard hook: PreToolUse (`Edit|Write|MultiEdit|NotebookEdit|Bash`) and ConfigChange, through
  `scripts/engstd_guard.py`, which finds eng-standards (`ENGSTD_ROOT`, `eng.toml`, the
  `_tools/eng-tools` submodule, the side-by-side layout) and runs its `guard_auditor.py`; not
  found is a visible warning, never a silent pass.
- Commands: `/eng-init`, `/eng-pin-bump`, `/eng-audit`, `/eng-onboard`.
- Marketplace manifest (`engstd-marketplace`), tests with mutants, neutrality scan.
