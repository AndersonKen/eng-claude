#!/usr/bin/env python3
"""Plugin hook shim: in an eng project session, run eng-standards' guard on this event.

What it is for: the guard stops a well-meaning project session from editing the auditor, the
tools or its own rules by mistake or through drift. It is not a sandbox against a session set
on defeating it. So the shim closes what an ordinary mistake or a one-line "fix" could open,
and makes every other way out visible.

**Scope.** A session is in scope when the git repo holding `CLAUDE_PROJECT_DIR` (where the
session started) shows an eng-tools submodule in ANY of four places: a gitlink (mode 160000)
at HEAD, a gitlink in the index (at `_tools/eng-tools`, or at a `.../_tools/eng-tools` path
`.gitmodules` gives with a URL whose last segment is `eng-tools` or `eng-tools.git`), the working-tree `.gitmodules`, or a `_tools/eng-tools/.git`. No one
slip - moving `_tools`, `git reset`, `git rm -r --cached .`, `git read-tree --empty` - clears
all four. A `.git` that git rejects is a visible warning. The per-call
`cwd` is never used. Not in scope - not a git repo, no such gitlink, or the repo is one of
the `<STD>` repos themselves - the shim exits 0 and prints nothing. `CLAUDE_PROJECT_DIR`
missing or not a directory is a visible warning, not a silent exit.

**Where the guard is - user settings only.** The plugin's `engstd_root` option, as saved in
`pluginConfigs` in the user settings file (`~/.claude/settings.json`, or the one in
`CLAUDE_CONFIG_DIR`). Project settings cannot set `pluginConfigs`, but their `env` can set
any variable for this process; so `ENGSTD_ROOT` and `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` are
never used in hook mode. When either is set and differs from the saved option, the shim says
so in a `systemMessage` and uses the saved option. Option unset or wrong: NOT GUARDED, visibly.
`ENGSTD_ROOT` is honoured only by `--where --use-env-override` (for tests and diagnosis).

**Contract** (the guard's, passed through): exit 0 allows, exit 2 with the reason on stderr
blocks. The guard runs in place, never copied: it locates what it protects from its own
`__file__` (ES-052). A guard that crashes keeps its non-zero exit.

Standard library only; behaves the same on Python 3.9 and later.
"""
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

GUARD_REL = Path("hooks") / "guard_auditor.py"
TAG = "eng-claude guard"
OVERRIDE_VARS = ("ENGSTD_ROOT", "CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT")
DEFAULT_SUB = "_tools/eng-tools"
# Programs are looked up only here, never on the PATH a project's settings may have set.
FIXED_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
WINDOWS = os.name == "nt"
# Windows: git is Git for Windows' own git.exe, in a folder Windows names (a known folder, read
# from the system, not from an environment variable a project's settings could set). A child
# found by name there would come from the parent's PATH: CreateProcess ignores the child's env.
# (known folder, path under it)
WINDOWS_GIT = (("ProgramFiles", "Git/cmd/git.exe"), ("ProgramFilesX86", "Git/cmd/git.exe"),
               ("UserProgramFiles", "Git/cmd/git.exe"), ("Profile", "scoop/apps/git/current/cmd/git.exe"))
KNOWN_FOLDERS = {   # FOLDERID_* GUIDs (KnownFolders.h)
    "ProgramFiles": "{905e63b6-c1bf-494e-b29c-65b732d3d21a}",
    "ProgramFilesX86": "{7c5a40ef-a0fb-4bfc-874a-c0f2e0b9fa8e}",
    "UserProgramFiles": "{5cd7aee2-2219-4a67-b85d-6c9ce15660cb}",
    "Profile": "{5e6c858f-0e22-4760-9afe-ea3317b67173}",
}


class ScopeError(Exception):
    """In scope could not be decided: say so, never exit silently."""


def _resolve(p):
    try:
        return Path(os.path.expanduser(str(p))).resolve()
    except (OSError, RuntimeError):
        return Path(os.path.expanduser(str(p)))


def _is_engstd(path):
    try:
        return path is not None and (Path(path) / GUARD_REL).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------- windows

def known_folder(name):
    """A Windows known folder (KNOWN_FOLDERS) as the system reports it, or None."""
    if not WINDOWS:
        return None
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(KNOWN_FOLDERS[name])
    g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
    except (OSError, AttributeError):
        return None
    try:
        return Path(out.value) if hr == 0 and out.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def git_exe():
    """Windows: Git for Windows' git.exe from a known folder (WINDOWS_GIT), else None."""
    for folder, rel in WINDOWS_GIT:
        base = known_folder(folder)
        if base is not None and (base / rel).is_file():
            return base / rel
    return None


def _same(a, b):
    """Windows paths compare without case: `_TOOLS/Eng-Tools` is `_tools/eng-tools` there."""
    return a.casefold() == b.casefold() if WINDOWS else a == b


# ---------------------------------------------------------------- scope

def _git(args, cwd, env):
    genv = {k: v for k, v in env.items() if not k.startswith("GIT_")}
    genv["PATH"] = FIXED_PATH
    exe = "git"
    if WINDOWS:
        found = git_exe()
        if found is None:
            raise OSError("Git for Windows is not installed in "
                          + ", ".join(f"<{f}>/{r}" for f, r in WINDOWS_GIT))
        exe, genv["PATH"] = str(found), str(found.parent)
    return subprocess.run([exe, "-C", str(cwd)] + args, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=genv, timeout=20)


def _is_eng_tools_submodule(path, url):
    """`_tools/eng-tools` itself, or a `.../_tools/eng-tools` path whose URL's last segment is
    `eng-tools` or `eng-tools.git`. Someone else's `*eng-tools` submodule does not count."""
    path = path.strip().strip("/")
    if _same(path, DEFAULT_SUB):
        return True
    last = re.split(r"[/:]", url.strip().rstrip("/"))[-1] if url else ""
    if WINDOWS:
        path, last = path.replace("\\", "/").casefold(), last.casefold()
    return last in ("eng-tools", "eng-tools.git") and path.endswith("/" + DEFAULT_SUB)


def _gitmodules_paths(text):
    """Submodule paths that are the eng-tools pin (see `_is_eng_tools_submodule`)."""
    out, cur = [], {}
    for line in (text or "").splitlines() + ["[end]"]:
        s = line.strip()
        if s.startswith("["):
            p, u = cur.get("path", ""), cur.get("url", "")
            if p and _is_eng_tools_submodule(p, u):
                out.append(p.strip())
            cur = {}
            continue
        m = re.match(r"^(path|url)\s*=\s*(.+)$", s)
        if m:
            cur[m.group(1)] = m.group(2).strip().strip('"')
    return out


def _read_regular(path):
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def project_repo(project_dir, env):
    """The top level of the repo holding project_dir when it is an eng project, else None.

    In scope if ANY of these holds, so that leaving scope takes several deliberate steps, not
    one slip (`git reset`, `git rm -r --cached .`, `git read-tree --empty` each clear only the
    index): an eng-tools gitlink at HEAD; one in the index; the working-tree `.gitmodules`
    naming an eng-tools submodule; a `_tools/eng-tools/.git` in the working tree.

    Raises ScopeError when it cannot be decided: git will not run, or a `.git` exists at or
    above project_dir but git does not accept it as a repo."""
    try:
        r = _git(["rev-parse", "--show-toplevel"], project_dir, env)
    except (OSError, subprocess.SubprocessError) as e:
        raise ScopeError(f"git could not run ({e})")
    if r.returncode != 0:
        here = _resolve(project_dir)
        for d in [here] + list(here.parents):
            if (d / ".git").exists() or (d / ".git").is_symlink():
                raise ScopeError(f"{d / '.git'} exists but git rejects the repo: "
                                 + (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["no message"])[-1])
        return None                                   # not a git repo: no submodule to record
    top = Path(r.stdout.decode().strip())
    if (top / DEFAULT_SUB / ".git").exists():
        return _resolve(top)
    if _gitmodules_paths(_read_regular(top / ".gitmodules")):
        return _resolve(top)
    paths = {DEFAULT_SUB}
    for spec in ("HEAD:.gitmodules", ":.gitmodules"):
        g = _git(["show", spec], top, env)
        if g.returncode == 0:
            paths.update(_gitmodules_paths(g.stdout.decode("utf-8", "replace")))
    for p in sorted(paths):
        for args in (["ls-tree", "HEAD", "--", p], ["ls-files", "-s", "--", p]):
            g = _git(args, top, env)
            if g.returncode == 0 and any(l.startswith("160000 ")
                                         for l in g.stdout.decode().splitlines()):
                return _resolve(top)
    return None


# ---------------------------------------------------------------- location

def _settings_file(env):
    if WINDOWS and not env.get("CLAUDE_CONFIG_DIR"):
        # Claude Code's `~/.claude` is %USERPROFILE%\.claude on Windows. Git Bash sets HOME to
        # a path of its own, so the profile folder comes from the system (known folder).
        profile = known_folder("Profile") or Path(env.get("USERPROFILE") or os.path.expanduser("~"))
        return profile / ".claude" / "settings.json"
    cfg = env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")
    return Path(cfg) / "settings.json"


def saved_option(env):
    """(value or None, settings path). Read only from a regular file, so a FIFO or device
    planted in its place cannot hang the hook."""
    f = _settings_file(env)
    try:
        if not stat.S_ISREG(os.stat(f).st_mode):
            return None, f
        with open(f, encoding="utf-8") as fh:
            configs = json.load(fh).get("pluginConfigs") or {}
    except (OSError, ValueError, AttributeError):
        return None, f
    if not isinstance(configs, dict):
        return None, f
    for key, val in configs.items():
        if key == "engstd" or str(key).startswith("engstd@"):
            for d in (val, val.get("options") if isinstance(val, dict) else None):
                if isinstance(d, dict) and isinstance(d.get("engstd_root"), str) and d["engstd_root"]:
                    return d["engstd_root"], f
    return None, f


def locate(env, use_env_override=False):
    """(eng-standards or None, notes). Notes are things the user must see: an override that
    was ignored, an option that is set but wrong, an option that is unset."""
    notes = []
    if use_env_override and env.get("ENGSTD_ROOT"):
        val = env["ENGSTD_ROOT"]
        if _is_engstd(_resolve(val)):
            return _resolve(val), ["using ENGSTD_ROOT (--use-env-override)"]
        return None, [f"ENGSTD_ROOT is {val!r}, which has no {GUARD_REL}"]
    saved, f = saved_option(env)
    saved_path = _resolve(saved) if saved else None
    for var in OVERRIDE_VARS:
        val = env.get(var)
        if val and (saved_path is None or _resolve(val) != saved_path):
            notes.append(f"{var}={val!r} is set in this session's environment and ignored; the "
                         f"guard location comes only from the engstd_root option in {f}")
    if saved is None:
        notes.append(f"the plugin's engstd_root option is not set (looked in {f}); set it in "
                     "/plugin or /config to the eng-standards checkout")
        return None, notes
    if not _is_engstd(saved_path):
        notes.append(f"the engstd_root option is {saved!r}, which has no {GUARD_REL}")
        return None, notes
    return saved_path, notes


def is_std_repo(top, engstd):
    for repo in (engstd, engstd.parent / "eng-tools"):
        try:
            top.relative_to(_resolve(repo))
            return True
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------- hook

def _say(text, stdout, stderr):
    msg = f"{TAG}: {text}"
    print(msg, file=stderr)
    print(json.dumps({"systemMessage": msg}), file=stdout)


def main(stdin=None, stdout=None, stderr=None, env=None, python=None):
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    env = os.environ if env is None else env
    raw = stdin.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    project_dir = env.get("CLAUDE_PROJECT_DIR")
    if not project_dir or not os.path.isdir(project_dir):
        _say(f"NOT GUARDED - CLAUDE_PROJECT_DIR is {'unset' if not project_dir else repr(project_dir) + ', not a directory'}, "
             "so this session cannot be placed in or out of an eng project. Allowing this call.",
             stdout, stderr)
        return 0
    try:
        top = project_repo(project_dir, env)
    except ScopeError as e:
        _say(f"NOT GUARDED - cannot tell whether {project_dir} is an eng project: {e}. "
             "Allowing this call.", stdout, stderr)
        return 0
    if top is None:
        return 0                                   # not an eng project: not the guard's session
    engstd, notes = locate(env)
    if engstd is not None and is_std_repo(top, engstd):
        return 0                                   # the owner's own <STD> repos
    if engstd is None:
        _say("NOT GUARDED - " + "; ".join(notes) + ". Allowing this call.", stdout, stderr)
        return 0
    guard = engstd / GUARD_REL
    try:
        # -I: the guard ignores PYTHON* variables a project's settings may have set.
        r = subprocess.run([python or sys.executable, "-I", str(guard)], input=raw,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=50)
    except (OSError, subprocess.SubprocessError) as e:
        _say(f"NOT GUARDED - could not run {guard} ({e}). Allowing this call.", stdout, stderr)
        return 0
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    if notes:
        # An ignored override is reported beside the guard's own answer, whatever it is.
        msg = f"{TAG}: " + "; ".join(notes)
        try:
            obj = json.loads(out) if out.strip().startswith("{") else None
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            obj["systemMessage"] = (obj.get("systemMessage", "") + " " + msg).strip()
            out = json.dumps(obj)
        elif not out.strip():
            out = json.dumps({"systemMessage": msg})
        err = msg + "\n" + err
    if out:
        stdout.write(out)
    if err:
        stderr.write(err)
    if r.returncode not in (0, 2):
        # The guard crashed: Claude Code shows a non-0/2 exit as a hook error notice, so the
        # failure is visible; pass the code through rather than turning it into a silent 0.
        if not r.stderr:
            stderr.write(f"{TAG}: {guard} exited {r.returncode} with no message\n")
    return r.returncode


def where(project_dir=None, stdout=None, env=None, use_env_override=False):
    """`--where [DIR] [--use-env-override]`: the eng-standards and eng-tools a session in DIR
    (default: the current directory) would use, with every ignored override named. Exit 0
    found, 1 not found."""
    stdout = stdout if stdout is not None else sys.stdout
    env = os.environ if env is None else env
    start = project_dir or os.getcwd()
    saved, f = saved_option(env)
    print(f"engstd_root option ({f}): {saved if saved else 'unset'}", file=stdout)
    for var in OVERRIDE_VARS:
        if env.get(var):
            print(f"{var} in the environment: {env[var]}"
                  + ("" if use_env_override and var == "ENGSTD_ROOT" else "  (ignored)"), file=stdout)
    engstd, notes = locate(env, use_env_override=use_env_override)
    for n in notes:
        print(f"note: {n}", file=stdout)
    try:
        top = project_repo(start, env) if os.path.isdir(start) else None
    except ScopeError:
        top = None
    print("eng project: " + (str(top) if top else f"no (no eng-tools gitlink recorded at {start})"),
          file=stdout)
    if engstd is None:
        print("NOT FOUND: the guard location is not configured or is wrong", file=stdout)
        return 1
    tools = engstd.parent / "eng-tools"
    print(f"eng-standards: {engstd}", file=stdout)
    print(f"eng-tools: {tools}" + ("" if tools.is_dir() else "  (MISSING: not cloned beside it)"),
          file=stdout)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--where"]:
        rest = sys.argv[2:]
        use = "--use-env-override" in rest
        rest = [a for a in rest if a != "--use-env-override"]
        sys.exit(where(rest[0] if rest else None, use_env_override=use))
    sys.exit(main())
