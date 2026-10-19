#!/bin/sh
# Hook launcher: run the shim with a fixed PATH and an isolated python3, so a PATH or PYTHON*
# variable from a project's settings `env` cannot swap the interpreter or its modules.
# On Windows this runs under Git for Windows' sh (Claude Code runs a shell-form hook in Git
# Bash there), and the interpreter is found through Windows' own folder lookup instead.
PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin
export PATH
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE
# The Windows py launcher reads these to choose an interpreter: a project's `env` must not.
unset PY_PYTHON PY_PYTHON3 PYLAUNCHER_ALLOW_INSTALL PYLAUNCHER_ALWAYS_INSTALL

# Cheap, shell-only guess at "is this an eng project session?" for the one case the shim
# cannot run at all. The shim makes the real decision whenever python3 exists.
likely_in_scope() {
    d=$CLAUDE_PROJECT_DIR
    [ -n "$d" ] || return 0                       # cannot tell: say so rather than stay silent
    [ -e "$d/_tools/eng-tools/.git" ] && return 0
    [ -f "$d/.gitmodules" ] || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in
            *path*=*_tools/eng-tools|*path*=*_tools/eng-tools[[:space:]]*) return 0 ;;
        esac
    done < "$d/.gitmodules"
    return 1
}

not_guarded() {
    while IFS= read -r ev || [ -n "$ev" ]; do ev=; done   # drain the event (builtins only: no PATH)
    if likely_in_scope; then
        printf '%s\n' "{\"systemMessage\": \"engstd guard: $1 - NOT GUARDED\"}"
    fi
    exit 0
}

# Windows: Git Bash's sh. A real Windows interpreter is looked for only in folders Windows
# itself names (cygpath -F asks the system for a known folder by its CSIDL number, not an
# environment variable): the py launcher first, then python.org installs, then the common
# conda bases and scoop. The Microsoft Store `python3` alias is never used: without the Store
# app it is a stub that opens the Store.
case $(uname -s 2>/dev/null) in
    MINGW*|MSYS*|CYGWIN*)
        win=$(cygpath -u -F 36 2>/dev/null)        # CSIDL_WINDOWS
        lad=$(cygpath -u -F 28 2>/dev/null)        # CSIDL_LOCAL_APPDATA
        pf=$(cygpath -u -F 38 2>/dev/null)         # CSIDL_PROGRAM_FILES
        home=$(cygpath -u -F 40 2>/dev/null)       # CSIDL_PROFILE
        for py in "$win/py.exe" "$lad/Programs/Python/Launcher/py.exe"; do
            if [ -f "$py" ]; then
                exec "$py" -3 -I "$(dirname "$0")/engstd_guard.py" "$@"
            fi
        done
        found=
        for py in "$lad"/Programs/Python/Python3*/python.exe "$pf"/Python3*/python.exe \
                  "$home"/miniforge3/python.exe "$home"/miniconda3/python.exe \
                  "$home"/anaconda3/python.exe "$home"/scoop/apps/python/current/python.exe; do
            [ -f "$py" ] && found=$py               # globs sort ascending: the newest wins
        done
        if [ -n "$found" ]; then
            exec "$found" -I "$(dirname "$0")/engstd_guard.py" "$@"
        fi
        not_guarded "no Python 3 found (py launcher, python.org, conda or scoop install)"
        ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
    not_guarded "no python3 on PATH ($PATH)"
fi
exec python3 -I "$(dirname "$0")/engstd_guard.py" "$@"
