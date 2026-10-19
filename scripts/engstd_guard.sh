#!/bin/sh
# Hook launcher: run the shim with a fixed PATH and an isolated python3, so a PATH or PYTHON*
# variable from a project's settings `env` cannot swap the interpreter or its modules.
PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin
export PATH
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE

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

if ! command -v python3 >/dev/null 2>&1; then
    while IFS= read -r ev || [ -n "$ev" ]; do ev=; done   # drain the event (builtins only: no PATH)
    if likely_in_scope; then
        printf '%s\n' "{\"systemMessage\": \"engstd guard: no python3 on PATH ($PATH) - NOT GUARDED\"}"
    fi
    exit 0
fi
exec python3 -I "$(dirname "$0")/engstd_guard.py" "$@"
