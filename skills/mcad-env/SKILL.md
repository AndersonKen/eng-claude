---
name: "mcad-env"
description: "Use whenever a task in any of the owner's projects needs CadQuery, gmsh, CalculiX (ccx), STEP export, FEA or the mcad-tools test suite: which environment to use, and how to run, verify and rebuild the Mac mcad env (reference, FEA) and the Cowork VM venv (CAD only)."
---

# The owner's mcad environments (CadQuery + gmsh + CalculiX)

Applies to every project, under any root, and any new one. The facts live in mcad-tools `env/README.md` and STANDARD §14.2: versions, verified test results and rebuild commands. Read the pinned copy, not this skill, for anything version-specific:

- every project repo: `_tools/eng-tools/mcad-tools/env/README.md`, under the repo's ECAD subfolder where it keeps its tools there

Below, `$T` means that `_tools/eng-tools/mcad-tools` directory. There is one copy of mcad-tools, the `eng-tools` submodule (SD-048); nothing is synced between repos.

## 1. Which environment

| Where Claude is running | Env | Use for |
|---|---|---|
| Claude Code on the owner's Mac | the `mcad` conda env, run by the absolute path of its `bin/python` (`<mcad python>`) | everything: CAD, drawings, checker, tests, **FEA**, attestations. The reference env (SD-046). |
| Cowork VM (device_bash, linux-aarch64) | `~/mcad-venv` (uv, pip-only, SD-040) | CAD, STEP export, drawings, `check_register.py`, `run_tests.py`. **No FEA.** |

- On the Mac, run it by absolute path. Never use `conda run`, and never bare `python3` (there it is an older Python with no CadQuery).
- Desktop Commander is not used for CAD.
- FEA results are cited only from the Mac `mcad` env.

## 2. Mac `mcad` env (reference)

Verify, and compare with the "Verified state" line in `$T/env/README.md`:

```sh
P="<mcad env prefix>"   # the env folder holding <mcad python>, i.e. its bin/python
$P/bin/python -c "import sys,platform,cadquery,gmsh,yaml,reportlab,matplotlib;print(sys.version.split()[0],platform.machine(),cadquery.__version__,gmsh.__version__,reportlab.Version,matplotlib.__version__)"
$P/bin/ccx -v 2>&1 | head -3
cd "$T" && PATH=$P/bin:$PATH $P/bin/python run_tests.py > /tmp/t.log 2>&1; echo EXIT $?; grep -n '^Ran \|^OK\|^FAILED' /tmp/t.log
```

- The machine must read `arm64`, and the suite must be OK with **0 skipped**. A skip here means gmsh or ccx is missing, and that is a real fault.
- FEA: `fea_run.py` refuses to solve unless `tests/test_fea.py` passed with nothing skipped (STANDARD §20). Do not cite a result it did not produce.
- Conda for this env: the miniforge `conda` that manages it (`$T/env/README.md`). Never use another conda install that lists the `defaults` channel.
- **Rebuild only from the lock, following `$T/env/README.md`.** Never rebuild from `conda env export --from-history`.
  - Any create that is not from the lock must set `CONDA_SUBDIR=osx-arm64`. Miniforge's base runs under Rosetta and would otherwise produce an x86_64 env (SD-046).
  - `conda rename` is broken in conda 23.1.0 with no env active. Rename by cloning, then removing the old env.

## 3. Cowork VM venv (CAD only)

The venv lives in the task's VM home, so a new Cowork task must rebuild it (about 2 minutes). Check first:

```sh
~/mcad-venv/bin/python -c "import sys,platform,cadquery;print(sys.version.split()[0],platform.machine(),cadquery.__version__)"
```

Compare the output with the VM "Verified state" line in `$T/env/README.md`. If the venv is missing, rebuild it from the pin file. The owner approved this recipe; changing the pins needs a new go-ahead:

Cowork mounts the connected folder at `$HOME/mnt/<folder name>`, so the path depends on which folder the owner connected. Seen so far: a whole project repo, or a project's ECAD subfolder. Find the pinned copy rather than typing a path:

```sh
T=$(find "$HOME/mnt" -maxdepth 6 -type d -path '*/_tools/eng-tools/mcad-tools' -not -path '*/_review/*' -not -path '*/_wt/*' -not -path '*worktree*' 2>/dev/null)
[ "$(printf '%s\n' "$T" | grep -c .)" = 1 ] && echo "T=$T" || { echo "need exactly one mcad-tools, found:"; printf '%s\n' "$T"; }
```

If it finds none or several, stop and ask the owner which project. Never fall back to a remembered path. Then rebuild:

```sh
python3 -m pip install --user uv
~/.local/bin/uv python install 3.11
~/.local/bin/uv venv -p 3.11 ~/mcad-venv
VIRTUAL_ENV=~/mcad-venv ~/.local/bin/uv pip install -r "$T/env/mcad-venv-linux-aarch64.pip.txt"
```

Why uv and Python 3.11: the VM's system Python is 3.10. PyPI and github.com are reachable from the VM. conda-forge (`conda.anaconda.org`, `micro.mamba.pm`) and `ports.ubuntu.com` are not (checked 2026-09-26). Don't re-probe them each task; re-check only if the owner says the allowlist changed.

Running things: each device_bash call is a fresh shell, with a 180 s limit. Quote paths, because the repos have spaces:

```sh
cd "$T"
~/mcad-venv/bin/python run_tests.py > /tmp/t.log 2>&1; echo EXIT $?; grep -n '^Ran \|^OK\|^FAILED' /tmp/t.log
```

- Expected: OK, with every skip an FEA test ("needs CadQuery, gmsh and ccx"). Any other skip or failure is real.
- Judge by the unittest summary. Negative tests print `ERROR …`/`FAIL` lines on purpose; those lines do not mean the run failed.
- Project checker: `~/mcad-venv/bin/python _tools/eng-tools/mcad-tools/check_register.py <project> --write-report`. FEA results needing a re-run show as stale. Do not re-run FEA in the VM.
- Pip wheels and conda-forge builds can differ even at the same CadQuery version. Rely on measured dimensions (tests), not byte-identical STEP files.
- Keep logs in `/tmp`. Copy one into the project's `docs/_gen/` only when it is evidence for a gate or report.

**Scope honesty:**
- FEA is NOT VERIFIED in the VM. Never cite `fea_run.py` results produced there, and never report skipped FEA checks as passed.
- The cloud container (x86_64) has conda-forge blocked too and is not used for CAD.
- Without a Mac shell, the owner runs the commands and shares the summary lines. Ask the owner before relying on that.

**FEA in the VM (pending):**
- It needs gmsh and CalculiX 2.23 from conda-forge. Ask the owner to allow `conda.anaconda.org` and `micro.mamba.pm` in the egress allowlist. Then install with micromamba into a separate env and pass the FEA verification tests with 0 skips before citing any result.
- Ubuntu's CalculiX (2.17) would need a standard-level decision plus passing verification.
- When this is done, update `env/README.md`, STANDARD §14 and this skill, and log a decision.

## 4. Change rules

- Installing, upgrading, recreating or deleting any env needs the owner's explicit go-ahead in the owner's own message. Rebuilding the VM venv from the approved pin file in a new task is already covered.
- Build replacements beside the old env, and swap only after `run_tests.py` passes (Mac: 0 skipped; VM: FEA skips only).
- After any change, follow "After any change to the env" in `env/README.md`:
  - regenerate the lock and pin files;
  - run `tests/test_env_lock.py`;
  - update the verified-state line and STANDARD §14;
  - log an SD decision.

  The change lands in `eng-tools` and reaches each project when its pin moves. Update this skill only if the *procedure* changed, not for a version bump.

## 5. Credit economy

- Run checks and tests as single shell calls printing only summary lines. Don't stream full logs into the conversation.
