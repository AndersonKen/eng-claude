#!/usr/bin/env python3
"""Prove the plugin's manifests, skills, commands and guard shim are what the docs and the
brief say, and that each check can fail.

    python3 tests/test_plugin.py             # the suite
    python3 tests/test_plugin.py --mutants   # also prove the tests catch a broken shim/checker
    python3 tests/test_plugin.py -k shim     # only tests whose name contains "shim"

Standard library only (PyYAML is used for frontmatter when present). Nothing is written
outside a temp dir, except while a mutant is applied: the mutated file is restored in a
`finally`, and `--mutants` refuses to start on a dirty tree so a crash cannot be mistaken for
the committed file.

Two tests need things outside this repo and say NOT CHECKED - never pass - without them:
the neutrality scan (eng-tools' `check_neutral.py` and its denylist, looked for beside this
repo or at `$ENGTOOLS_ROOT`) and `claude plugin validate` (the `claude` CLI on PATH).
"""
import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHIM = ROOT / "scripts" / "engstd_guard.py"
LAUNCHER = ROOT / "scripts" / "engstd_guard.sh"
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

import plugin_checks as C  # noqa: E402

SKILLS = ("ecad-design-document", "mechanical-engineering-standard", "mcad-env",
          "git-concurrent-sessions", "refresh-program-board")
COMMANDS = ("eng-init", "eng-pin-bump", "eng-audit", "eng-onboard")
ASK_FIRST = ("commit", "push", "remote", "install", "outside", "hooks or settings", "deleting",
             "fetched")

# A stand-in guard with the real one's contract (exit 2 + stderr blocks, 0 allows) that
# self-locates the way the real one does (ES-052): it protects the folder it sits in, and,
# like the real one, a CLAUDE.md anywhere.
STUB_GUARD = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
AUDITOR = Path(__file__).resolve().parents[1]
ev = json.load(sys.stdin)
ti = ev.get("tool_input", {})
if ti.get("file_path") == "CRASH":
    sys.exit(1)
if ev.get("hook_event_name") == "ConfigChange":
    print("blocked by stub guard: settings", file=sys.stderr); sys.exit(2)
p = ti.get("file_path") or ""
if p and (Path(os.path.realpath(p)).as_posix().startswith(AUDITOR.as_posix() + "/")
          or p.endswith("CLAUDE.md")):
    print("blocked by stub guard: " + AUDITOR.name, file=sys.stderr); sys.exit(2)
# A command names the folder in `\` or `/`, any case, long or 8.3 form on Windows (ES-069).
cmd = (ti.get("command") or "").replace("\\", "/").casefold()
if any(a.as_posix().casefold() in cmd for a in (AUDITOR, Path(os.path.abspath(__file__)).parents[1])):
    print("blocked by stub guard: bash on " + AUDITOR.name, file=sys.stderr); sys.exit(2)
sys.exit(0)
'''
# A guard that waves everything through: what a session would plant to switch the real one off.
PERMISSIVE_GUARD = "import sys\nsys.exit(0)\n"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}
FAKE_SHA = "0" * 39 + "1"


class NotChecked(Exception):
    """The check could not run here. Reported as NOT CHECKED, never as a pass."""


def eng_tools_dir():
    env = os.environ.get("ENGTOOLS_ROOT")
    return Path(env) if env else ROOT.parent / "eng-tools"


WINDOWS = os.name == "nt"
# Windows will not start a process (Python included) without these; a test's minimal env keeps
# them, and nothing the guard decides depends on them.
WINDOWS_BASE = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT")


def only_on(*platforms):
    """A test that can run only on these `os.name`s ("nt", "posix"): it is not collected
    elsewhere, so another platform neither runs it nor reports it NOT CHECKED."""
    def mark(fn):
        fn.platforms = platforms
        return fn
    return mark


def base_env(**kw):
    """A minimal environment: on Windows, the variables a process needs to start, plus kw."""
    env = {k: os.environ[k] for k in WINDOWS_BASE if WINDOWS and k in os.environ}
    env.update(kw)
    return env


def _shim_module():
    sys.path.insert(0, str(SHIM.parent))
    try:
        import engstd_guard
        return engstd_guard
    finally:
        sys.path.remove(str(SHIM.parent))


def posix_sh():
    """The sh a shell-form hook reaches as `/bin/sh`: /bin/sh, or Git for Windows' sh.exe."""
    if not WINDOWS:
        return "/bin/sh"
    git_exe = _shim_module().git_exe()
    if git_exe is None:
        raise NotChecked("Git for Windows not found: no sh to run the launcher with")
    return str(git_exe.parent.parent / "usr" / "bin" / "sh.exe")


def hook_shell():
    """argv prefix Claude Code uses for a shell-form hook: `sh -c`, or Git Bash on Windows."""
    if not WINDOWS:
        return ["/bin/sh", "-c"]
    return [str(Path(posix_sh()).parent.parent.parent / "bin" / "bash.exe"), "-c"]


# ---------------------------------------------------------------- fixtures

def git(cwd, *args, check=True):
    env = dict(os.environ, HOME=str(cwd), **GIT_ENV)
    r = subprocess.run(["git", "-C", str(cwd)] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    if check and r.returncode:
        raise AssertionError(f"git {args}: {r.stderr.decode()}")
    return r.stdout.decode()


def make_std(tmp, guard_text=STUB_GUARD, name="std"):
    std = tmp / name
    (std / "eng-standards" / "hooks").mkdir(parents=True)
    (std / "eng-tools").mkdir()
    (std / "eng-standards" / "hooks" / "guard_auditor.py").write_text(guard_text, encoding="utf-8", newline="\n")
    return std


def make_repo(tmp, name, sub_path=None, commit=True):
    """A git repo; with sub_path, an eng-tools gitlink (mode 160000) recorded there."""
    p = tmp / name
    p.mkdir(parents=True)
    git(p, "init", "-q")
    (p / "README").write_text("x\n", encoding="utf-8", newline="\n")
    git(p, "add", "README")
    if sub_path:
        (p / ".gitmodules").write_text(f'[submodule "{sub_path}"]\n\tpath = {sub_path}\n'
                                       "\turl = https://example.invalid/eng-tools.git\n", encoding="utf-8", newline="\n")
        (p / sub_path).mkdir(parents=True)
        git(p, "add", ".gitmodules")
        git(p, "update-index", "--add", "--cacheinfo", f"160000,{FAKE_SHA},{sub_path}")
    if commit:
        git(p, "commit", "-q", "-m", "init")
    return p


def make_project(tmp, name="proj", sub_path="_tools/eng-tools"):
    return make_repo(tmp, name, sub_path)


def settings_dir(tmp):
    """On Windows the shim reads the profile folder's settings (from the system, not HOME), so a
    test names its own with CLAUDE_CONFIG_DIR there; elsewhere HOME already does."""
    return {"CLAUDE_CONFIG_DIR": str(tmp / "home" / ".claude")} if WINDOWS else {}


def set_option(tmp, value, key="engstd@engstd-marketplace"):
    cfg = tmp / "home" / ".claude"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps({"pluginConfigs": {key: {"engstd_root": str(value)}}}), encoding="utf-8", newline="\n")


def run_shim(event, tmp, project_dir=None, env_extra=None, raw=None):
    """Run the shim the way Claude Code does: a process, the event on stdin, the project dir in
    CLAUDE_PROJECT_DIR. HOME is a temp folder, so the user settings (and the saved option) are
    the test's own, never the machine's."""
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = base_env(PATH=os.environ.get("PATH", "/usr/bin:/bin"), HOME=str(home),
                   CLAUDE_PLUGIN_ROOT=str(ROOT), **settings_dir(tmp))
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.update(env_extra or {})
    data = raw if raw is not None else json.dumps(event).encode()
    r = subprocess.run([sys.executable, str(SHIM)], input=data, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, timeout=60)
    return r.returncode, r.stdout.decode(), r.stderr.decode()


def edit(path, cwd):
    return {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(cwd),
            "tool_input": {"file_path": str(path)}}


def bash(command, cwd):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
            "tool_input": {"command": command}}


def config_change(source, cwd):
    return {"hook_event_name": "ConfigChange", "source": source, "cwd": str(cwd),
            "file_path": str(Path(cwd) / ".claude" / "settings.json")}


def system_message(out):
    lines = out.strip().splitlines()
    return json.loads(lines[-1]).get("systemMessage", "") if lines else ""


def assert_warned(code, out, err, needle="NOT GUARDED"):
    assert code == 0, f"expected allow (0), got {code}: {err}"
    assert needle in err, f"no visible warning on stderr: {err!r}"
    assert needle in system_message(out), f"no systemMessage for the user: {out!r}"


def assert_silent_allow(code, out, err):
    assert (code, out.strip(), err.strip()) == (0, "", ""), (code, out, err)


def guarded(tmp):
    """A temp <STD> with the stub guard, the saved option pointing at it, and a project."""
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    return std, make_project(tmp)


# ---------------------------------------------------------------- manifests and content

def test_the_real_tree_passes_every_structural_check(tmp):
    problems = C.check_all(ROOT)
    assert not problems, "\n".join(problems)


def test_plugin_and_marketplace_agree_and_the_version_is_in_the_changelog(tmp):
    p = C.load_json(ROOT / ".claude-plugin" / "plugin.json")
    m = C.load_json(ROOT / ".claude-plugin" / "marketplace.json")
    entry = [e for e in m["plugins"] if e["name"] == p["name"]]
    assert entry, "the marketplace does not list this plugin"
    assert entry[0]["source"] in ("./", "."), entry[0]["source"]
    assert "version" not in entry[0], "version set in both places; plugin.json wins silently"
    top = re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert top and top.group(1) == p.get("version"), (p.get("version"), top and top.group(1))


def test_plugin_declares_the_engstd_root_option(tmp):
    opt = C.load_json(ROOT / ".claude-plugin" / "plugin.json")["userConfig"]["engstd_root"]
    assert opt["type"] == "directory" and opt["title"] and opt["description"], opt
    assert "pluginConfigs" in SHIM.read_text(encoding="utf-8"), "the shim does not read the saved option"


# Shell form (no `args`): sh -c on macOS and Linux, Git Bash on Windows. The exec form
# (`"command": "/bin/sh"` with `args`) is spawned with no shell, and on Windows `/bin/sh` is
# no executable at all, so every call would be a hook error there (ES-069). Inside either shell
# `/bin/sh` is absolute, so the session's PATH still never picks it.
GUARD_COMMAND = '/bin/sh "${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.sh"'


def _is_guard_hook(x):
    return x.get("command") == GUARD_COMMAND and "args" not in x and "shell" not in x


def test_hooks_cover_the_guard_events_and_tools(tmp):
    h = C.load_json(ROOT / "hooks" / "hooks.json")["hooks"]
    tools = set()
    for g in h["PreToolUse"]:
        tools |= set(g["matcher"].split("|"))
        assert any(_is_guard_hook(x) for x in g["hooks"]), g
    # PowerShell is Claude Code's shell tool on Windows beside Bash (docs: match Bash|PowerShell).
    assert tools == {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}, tools
    sources = set()
    for g in h["ConfigChange"]:
        sources |= set(g.get("matcher", "*").split("|"))
        assert any(_is_guard_hook(x) for x in g["hooks"]), g
    # Settings changes are guarded; skill reloads are not (docs: ConfigChange matcher values).
    assert {"user_settings", "project_settings", "local_settings"} <= sources, sources
    assert "skills" not in sources and "*" not in sources, sources


def test_all_five_skills_are_there_with_frontmatter(tmp):
    for s in SKILLS:
        f = ROOT / "skills" / s / "SKILL.md"
        assert f.is_file(), f"missing {f}"
        fm = C.parse_frontmatter(f.read_text(encoding="utf-8"))
        assert fm and fm.get("name") == s and fm.get("description"), (s, fm)


def test_every_command_parses_and_states_the_ask_first_list(tmp):
    for c in COMMANDS:
        f = ROOT / "commands" / f"{c}.md"
        assert f.is_file(), f"missing {f}"
        text = f.read_text(encoding="utf-8")
        fm = C.parse_frontmatter(text)
        assert fm and fm.get("description"), (c, fm)
        body = text.lower()
        missing = [w for w in ASK_FIRST if w not in body]
        assert not missing, f"{c}.md does not state: {missing}"


def test_init_dry_runs_first_and_names_what_the_real_run_writes(tmp):
    init = (ROOT / "commands" / "eng-init.md").read_text(encoding="utf-8")
    assert "--dry-run" in init and init.index("--dry-run") < init.index("Real run"), "no dry run first"
    ask = init[init.index("2. **Ask"):init.index("3. **Real run")]
    assert "CLAUDE.md" in ask and ".claude/settings.json" in ask, "the ask does not name the settings files"


def test_pin_bump_dry_run_then_one_commit_run_then_a_plain_push(tmp):
    pin = (ROOT / "commands" / "eng-pin-bump.md").read_text(encoding="utf-8")
    steps = pin[pin.index("## Steps"):]
    assert steps.index("--dry-run") < steps.index("--commit") < steps.index("git -C <project-repo> push")
    assert "--push" not in steps, "the command still pushes through the script"
    # ES-059: the guard refuses --commit from a session, so the user runs the committing step.
    assert '! python3 "<eng-tools>/bin/pin_bump.py"' in steps, "the committing run is not handed to the user"
    assert "Do not run it yourself" in steps, "the command lets Claude run the committing step"


def test_audit_reports_rows_not_exit_codes_and_never_folds_missing_into_pass(tmp):
    a = (ROOT / "commands" / "eng-audit.md").read_text(encoding="utf-8")
    for needle in ("check_standard.py", "check_sch.py", "--all", "check_register.py",
                   "_tools/eng-tools", "MISSING is never", "exits 2 when it printed every row",
                   "**WARN**", "**n/a**"):
        assert needle in a, needle


def _script_help(script):
    env = os.environ.get("ENGTOOLS_BIN")
    path = Path(env) / script if env else eng_tools_dir() / "bin" / script
    if not path.is_file():
        return None, path
    r = subprocess.run([sys.executable, str(path), "--help"], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=60)
    return r.stdout.decode(), path


def test_command_flags_exist_in_the_scripts_help(tmp):
    absent = []
    for cmd, script in (("eng-init", "init_project.py"), ("eng-pin-bump", "pin_bump.py")):
        text = (ROOT / "commands" / f"{cmd}.md").read_text(encoding="utf-8")
        used = set(re.findall(r"(--[a-z][a-z-]+)", text)) - {"--help", "--where", "--show-toplevel",
                                                           "--abbrev-ref", "--symbolic-full-name",
                                                           "--short", "--stat"}
        help_text, path = _script_help(script)
        if help_text is None:
            absent.append(str(path))
            continue
        unknown = sorted(f for f in used if f not in help_text)
        assert not unknown, f"{cmd}.md uses flags {script} --help does not list: {unknown}"
    if absent:
        raise NotChecked("scripts not found: " + ", ".join(absent))


# ---------------------------------------------------------------- the checkers fail on bad input

def _copy_tree(tmp):
    dst = tmp / "plugin"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return dst


def test_checks_flag_a_skill_with_no_frontmatter(tmp):
    d = _copy_tree(tmp)
    (d / "skills" / "mcad-env" / "SKILL.md").write_text("# no frontmatter here\n", encoding="utf-8", newline="\n")
    assert any("no frontmatter" in p for p in C.check_skills(d)), C.check_skills(d)


def test_checks_flag_a_skill_with_no_description(tmp):
    d = _copy_tree(tmp)
    (d / "skills" / "mcad-env" / "SKILL.md").write_text("---\nname: mcad-env\n---\nbody\n", encoding="utf-8", newline="\n")
    assert any("description" in p for p in C.check_skills(d)), C.check_skills(d)


def test_checks_flag_a_command_whose_frontmatter_does_not_parse(tmp):
    d = _copy_tree(tmp)
    (d / "commands" / "eng-audit.md").write_text("---\ndescription: \"unclosed\n---\nbody\n", encoding="utf-8", newline="\n")
    assert C.check_commands(d), "a broken command file passed"


def test_checks_flag_a_plugin_json_without_a_name(tmp):
    d = _copy_tree(tmp)
    f = d / ".claude-plugin" / "plugin.json"
    m = C.load_json(f)
    del m["name"]
    f.write_text(json.dumps(m), encoding="utf-8", newline="\n")
    assert any("`name` is required" in p for p in C.check_plugin_manifest(d))


def test_checks_flag_a_marketplace_without_an_owner(tmp):
    d = _copy_tree(tmp)
    f = d / ".claude-plugin" / "marketplace.json"
    m = C.load_json(f)
    del m["owner"]
    f.write_text(json.dumps(m), encoding="utf-8", newline="\n")
    assert any("owner" in p for p in C.check_marketplace(d))


def test_checks_flag_a_source_that_climbs_out(tmp):
    d = _copy_tree(tmp)
    f = d / ".claude-plugin" / "marketplace.json"
    m = C.load_json(f)
    m["plugins"][0]["source"] = "./../elsewhere"
    f.write_text(json.dumps(m), encoding="utf-8", newline="\n")
    assert any("contains .." in p for p in C.check_marketplace(d)), C.check_marketplace(d)


def test_checks_flag_a_hooks_file_without_the_wrapper(tmp):
    d = _copy_tree(tmp)
    f = d / "hooks" / "hooks.json"
    f.write_text(json.dumps(C.load_json(f)["hooks"]), encoding="utf-8", newline="\n")
    assert any("top-level" in p for p in C.check_hooks(d)), C.check_hooks(d)


def test_fallback_frontmatter_parser_without_pyyaml(tmp):
    """The checks must hold on a machine without PyYAML, where the line parser decides."""
    saved = sys.modules.get("yaml", "absent")
    sys.modules["yaml"] = None                     # makes `import yaml` raise ImportError
    try:
        for f in sorted((ROOT / "skills").glob("*/SKILL.md")) + sorted((ROOT / "commands").glob("*.md")):
            fm = C.parse_frontmatter(f.read_text(encoding="utf-8"))
            assert fm and fm.get("description"), f
        for bad in ('---\ndescription: "unclosed\n---\n', "---\nnot a key line\n---\n",
                    "---\ndescription: x\n"):
            try:
                C.parse_frontmatter(bad)
            except C.FrontmatterError:
                continue
            raise AssertionError(f"fallback parser accepted {bad!r}")
    finally:
        if saved == "absent":
            del sys.modules["yaml"]
        else:
            sys.modules["yaml"] = saved


# ---------------------------------------------------------------- the guard shim: scope

def test_scope_project_session_edit_into_eng_standards_is_blocked(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(edit(std / "eng-standards" / "lights.yaml", proj), tmp, proj)
    assert code == 2 and "blocked by stub guard" in err, (code, err)


def test_scope_project_session_ordinary_edit_is_silent(tmp):
    std, proj = guarded(tmp)
    assert_silent_allow(*run_shim(edit(proj / "notes.md", proj), tmp, proj))


def test_scope_a_subfolder_of_a_project_is_still_the_project(tmp):
    std, proj = guarded(tmp)
    (proj / "boards" / "b1").mkdir(parents=True)
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj / "boards" / "b1")
    assert code == 2, (code, err)


def test_scope_a_submodule_at_a_gitmodules_path_counts(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    proj = make_project(tmp, sub_path="ECAD/_tools/eng-tools")
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
    assert code == 2, (code, err)


def test_scope_a_staged_but_uncommitted_submodule_counts(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    proj = make_repo(tmp, "fresh", "_tools/eng-tools", commit=False)
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
    assert code == 2, (code, err)


def test_scope_moving_tools_in_the_working_tree_does_not_escape(tmp):
    """Known-bad (N3): the working-tree checkout is moved away, uncommitted."""
    std, proj = guarded(tmp)
    shutil.rmtree(proj / "_tools")
    (proj / ".gitmodules").unlink()
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
    assert code == 2, f"scope escaped by an uncommitted move: exit {code}"


def test_scope_a_plain_tools_folder_is_not_a_submodule(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    other = make_repo(tmp, "other")
    (other / "_tools" / "eng-tools").mkdir(parents=True)          # no .git, no gitlink, no .gitmodules
    assert_silent_allow(*run_shim(edit(other / "CLAUDE.md", other), tmp, other))


def _fresh_init_repo(tmp):
    """What /eng-init leaves: submodule staged (gitlink + .gitmodules), checkout with its .git
    file, nothing committed beyond the first commit."""
    proj = make_repo(tmp, "fresh")
    (proj / ".gitmodules").write_text('[submodule "_tools/eng-tools"]\n\tpath = _tools/eng-tools\n'
                                      "\turl = https://example.invalid/eng-tools.git\n", encoding="utf-8", newline="\n")
    (proj / "_tools" / "eng-tools").mkdir(parents=True)
    git(proj / "_tools" / "eng-tools", "init", "-q")                 # the checkout's own .git
    git(proj, "add", ".gitmodules")
    git(proj, "update-index", "--add", "--cacheinfo", f"160000,{FAKE_SHA},_tools/eng-tools")
    return proj


def test_scope_one_slip_on_a_fresh_init_repo_does_not_escape(tmp):
    """Known-bad (round 3 B2): each of these clears only the index."""
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    for slip in (["reset", "-q"], ["rm", "-r", "-q", "--cached", "-f", "."], ["read-tree", "--empty"]):
        sub = tmp / ("t-" + slip[0])
        sub.mkdir()
        proj = _fresh_init_repo(sub)
        git(proj, *slip)
        assert "160000" not in git(proj, "ls-files", "-s"), "the slip did not clear the index"
        code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
        assert code == 2, f"`git {' '.join(slip)}` took the session out of scope: exit {code}"


def test_scope_each_signal_alone_keeps_the_session_in_scope(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    cases = {}
    p = make_repo(tmp / "a", "only-dotgit")                          # only _tools/eng-tools/.git
    (p / "_tools" / "eng-tools").mkdir(parents=True)
    (p / "_tools" / "eng-tools" / ".git").write_text("gitdir: x\n", encoding="utf-8", newline="\n")
    cases["working-tree _tools/eng-tools/.git"] = p
    p = make_repo(tmp / "b", "only-gitmodules")                      # only the working-tree .gitmodules
    (p / ".gitmodules").write_text('[submodule "x"]\n\tpath = ECAD/_tools/eng-tools\n'
                                   "\turl = git@example.invalid:o/eng-tools.git\n", encoding="utf-8", newline="\n")
    cases["working-tree .gitmodules"] = p
    p = make_project(tmp / "c", "only-head")                         # only the gitlink at HEAD
    git(p, "rm", "-r", "-q", "--cached", ".")
    shutil.rmtree(p / "_tools")
    (p / ".gitmodules").unlink()
    cases["gitlink at HEAD"] = p
    p = make_repo(tmp / "d", "only-index", "_tools/eng-tools", commit=False)   # only the index
    shutil.rmtree(p / "_tools")
    (p / ".gitmodules").unlink()
    cases["gitlink in the index"] = p
    for what, proj in cases.items():
        code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
        assert code == 2, f"{what} alone did not keep the session in scope: exit {code} {err}"


def test_scope_a_git_dir_that_git_rejects_warns_visibly(tmp):
    """Known-bad (round 3 S2): a broken .git must not read as 'not a repo'."""
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    broken = tmp / "broken"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /nonexistent/path\n", encoding="utf-8", newline="\n")
    assert_warned(*run_shim(edit(broken / "a", broken), tmp, broken), needle="git rejects")


def test_scope_unrelated_repo_is_silent_even_for_claude_md(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    other = make_repo(tmp, "unrelated")
    assert_silent_allow(*run_shim(edit(other / "CLAUDE.md", other), tmp, other))


def test_scope_a_folder_that_is_not_a_repo_is_silent(tmp):
    plain = tmp / "plain"
    plain.mkdir()
    assert_silent_allow(*run_shim(edit(plain / "a.txt", plain), tmp, plain))


def test_scope_the_std_repos_themselves_are_not_guarded(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    shutil.rmtree(std / "eng-tools")
    make_repo(std, "eng-tools", "_tools/eng-tools")      # even one recording an eng-tools gitlink
    git(std / "eng-standards", "init", "-q")
    for repo in (std / "eng-standards", std / "eng-tools"):
        assert_silent_allow(*run_shim(edit(std / "eng-standards" / "lights.yaml", repo), tmp, repo))


def test_scope_uses_the_project_dir_not_the_per_call_cwd(tmp):
    std, proj = guarded(tmp)
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    code, out, err = run_shim(edit(std / "eng-standards" / "x", elsewhere), tmp, proj)
    assert code == 2, (code, err)
    other = make_repo(tmp, "unrelated")
    assert_silent_allow(*run_shim(edit(other / "CLAUDE.md", proj), tmp, other))


def test_scope_missing_project_dir_warns_visibly(tmp):
    std, proj = guarded(tmp)
    assert_warned(*run_shim(edit(proj / "a", proj), tmp, None), needle="CLAUDE_PROJECT_DIR")


def test_scope_a_project_dir_that_is_not_a_directory_warns_visibly(tmp):
    """Known-bad (N3): a bogus CLAUDE_PROJECT_DIR must not read as 'out of scope'."""
    std, proj = guarded(tmp)
    assert_warned(*run_shim(edit(proj / "a", proj), tmp, tmp / "no-such-dir"), needle="not a directory")


# ---------------------------------------------------------------- the guard shim: where the guard is

def test_locate_from_the_saved_option(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)
    assert code == 2 and "blocked by stub guard" in err, (code, err)


def test_locate_the_option_under_an_options_key(tmp):
    std = make_std(tmp)
    proj = make_project(tmp)
    cfg = tmp / "home" / ".claude"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"engstd@m": {"options": {"engstd_root": str(std / "eng-standards")}}}}), encoding="utf-8", newline="\n")
    assert run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj)[0] == 2


def test_locate_env_overrides_from_project_settings_are_ignored_and_reported(tmp):
    """Known-bad (N1): project settings `env` repoints the guard at a permissive one."""
    std, proj = guarded(tmp)
    fake = make_std(tmp, guard_text=PERMISSIVE_GUARD, name="fake")
    for var in ("ENGSTD_ROOT", "CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT"):
        code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj,
                                  {var: str(fake / "eng-standards")})
        assert code == 2, f"{var} switched the guard: exit {code}"
        assert f"{var}=" in err and "ignored" in err, err
        code, out, err = run_shim(edit(proj / "ok.md", proj), tmp, proj, {var: str(fake / "eng-standards")})
        assert code == 0 and "ignored" in system_message(out), (code, out)


def test_locate_env_override_without_a_saved_option_is_not_used(tmp):
    """Known-bad (N1): with the option unset, an env var must not supply the guard."""
    std = make_std(tmp)
    fake = make_std(tmp, guard_text=PERMISSIVE_GUARD, name="fake")
    proj = make_project(tmp)
    for var in ("ENGSTD_ROOT", "CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT"):
        code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj,
                                  {var: str(fake / "eng-standards")})
        assert_warned(code, out, err)
        assert "ignored" in err and "not set" in err, err


def test_locate_an_env_value_equal_to_the_option_is_quiet(tmp):
    std, proj = guarded(tmp)
    assert_silent_allow(*run_shim(edit(proj / "a.md", proj), tmp, proj,
                                  {"CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT": str(std / "eng-standards")}))


def test_locate_a_wrong_saved_option_warns(tmp):
    std = make_std(tmp)
    set_option(tmp, tmp / "not-there")
    proj = make_project(tmp)
    code, out, err = run_shim(edit(proj / "a.txt", proj), tmp, proj)
    assert_warned(code, out, err)
    assert "has no" in err, err


def test_locate_unset_option_in_a_project_warns_visibly(tmp):
    proj = make_project(tmp)
    code, out, err = run_shim(edit(proj / "a.txt", proj), tmp, proj)
    assert_warned(code, out, err)
    assert "engstd_root option is not set" in err, err


def test_locate_a_local_submodule_url_is_not_a_fallback(tmp):
    """Known-bad (N3): fallback 3 is gone; a file:// submodule URL does not locate the guard."""
    std = make_std(tmp)
    proj = make_project(tmp)
    (proj / ".gitmodules").write_text('[submodule "_tools/eng-tools"]\n\tpath = _tools/eng-tools\n'
                                      f"\turl = file://{std / 'eng-tools'}\n", encoding="utf-8", newline="\n")
    assert_warned(*run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj))


@only_on("posix")                          # os.mkfifo: no FIFOs on Windows
def test_locate_a_fifo_in_place_of_the_settings_file_does_not_hang(tmp):
    proj = make_project(tmp)
    cfg = tmp / "home" / ".claude"
    cfg.mkdir(parents=True)
    os.mkfifo(cfg / "settings.json")
    code, out, err = run_shim(edit(proj / "a.txt", proj), tmp, proj)   # run_shim times out at 60 s
    assert_warned(code, out, err)


def test_bypass_eng_toml_and_cwd_stub_cannot_switch_the_guard_off(tmp):
    """Known-bad (B2): a session writes an eng.toml pointing at a permissive guard and cd's
    into a folder that holds one. Edits to eng-standards stay blocked."""
    std, proj = guarded(tmp)
    fake = make_std(tmp, guard_text=PERMISSIVE_GUARD, name="fake")
    (proj / "eng.toml").write_text(f'eng_standards = "{fake / "eng-standards"}"\n', encoding="utf-8", newline="\n")
    (proj / "hooks").mkdir()
    (proj / "hooks" / "guard_auditor.py").write_text(PERMISSIVE_GUARD, encoding="utf-8", newline="\n")
    for cwd in (proj, fake / "eng-tools", fake / "eng-standards"):
        code, out, err = run_shim(edit(std / "eng-standards" / "lights.yaml", cwd), tmp, proj)
        assert code == 2, f"guard switched off from cwd {cwd}: exit {code}"


# ---------------------------------------------------------------- the guard shim: events

def native():
    """Claude Code runs hooks natively. A test interpreter running under Rosetta (x86_64 on
    arm64) would start the launcher translated, and the system python3 stub cannot spawn its
    arm64 binary from there; so spawn the launcher as the host architecture."""
    if sys.platform != "darwin":
        return []
    r = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    return ["/usr/bin/arch", "-arm64"] if r.stdout.strip() == b"1" else []


def _fake_tools(tmp):
    """A folder of impostor `python3` and `git` that leave a marker if they ever run."""
    fake = tmp / "fakebin"
    fake.mkdir()
    for prog in ("python3", "git"):
        (fake / prog).write_text(f"#!/bin/sh\ntouch '{tmp}/ran-fake-{prog}'\nexit 0\n", encoding="utf-8", newline="\n")
        (fake / prog).chmod(0o755)
    return fake


def test_launcher_and_git_ignore_the_sessions_path_and_python_env(tmp):
    """Known-bad (round 3 S1): a project's settings `env` puts impostors first on PATH and a
    PYTHONPATH with a sitecustomize; neither is used."""
    std, proj = guarded(tmp)
    fake = _fake_tools(tmp)
    (fake / "sitecustomize.py").write_text(f"open('{tmp}/ran-sitecustomize', 'w').close()\n", encoding="utf-8", newline="\n")
    # PYTHONVERBOSE is not unset by the launcher: only `python3 -I` keeps it from printing the
    # interpreter's import trace.
    env = base_env(PATH=f"{fake}{os.pathsep}{os.environ.get('PATH', '')}", PYTHONPATH=str(fake),
                   PYTHONVERBOSE="1", HOME=str(tmp / "home"), CLAUDE_PROJECT_DIR=str(proj),
                   **settings_dir(tmp))
    ev = json.dumps(edit(std / "eng-standards" / "x", proj)).encode()
    r = subprocess.run(native() + [posix_sh(), LAUNCHER.as_posix()], input=ev, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, timeout=60)
    if WINDOWS and b"no Python 3 found" in r.stdout:
        raise NotChecked("no Python in the folders the Windows launcher searches: " + r.stdout.decode())
    assert r.returncode == 2 and b"blocked by stub guard" in r.stderr, (r.returncode, r.stderr[-400:])
    assert b"zipimport" not in r.stderr and b"\nimport " not in r.stderr, "PYTHON* reached the interpreter"
    # The shim run directly (as the tests do) must still find git on its fixed PATH only.
    code, out, err = run_shim(edit(std / "eng-standards" / "x", proj), tmp, proj, {"PATH": env["PATH"]})
    assert code == 2, (code, err)
    ran = sorted(p.name for p in tmp.glob("ran-*"))
    assert not ran, f"impostors ran: {ran}"


def _launcher_without_python(tmp):
    """A copy of the launcher whose fixed PATH is an empty folder: no python3 anywhere."""
    empty = tmp / "emptybin"
    empty.mkdir()
    text = LAUNCHER.read_text(encoding="utf-8")
    fixed = "PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
    assert text.count(fixed) == 1, "the launcher's fixed PATH line moved"
    copy = tmp / "launcher.sh"
    copy.write_text(text.replace(fixed, f"PATH='{empty.as_posix()}'"), newline="\n", encoding="utf-8")
    return copy


def test_launcher_without_python3_warns_in_a_project_and_is_silent_elsewhere(tmp):
    copy = _launcher_without_python(tmp)
    proj = tmp / "proj"
    (proj / "_tools" / "eng-tools" / ".git").mkdir(parents=True)
    by_modules = tmp / "by-modules"
    by_modules.mkdir()
    (by_modules / ".gitmodules").write_text('[submodule "x"]\n\tpath = ECAD/_tools/eng-tools\n', encoding="utf-8", newline="\n")
    other = tmp / "other"
    other.mkdir()
    for d, warned in ((proj, True), (by_modules, True), (other, False), (None, True)):
        env = base_env(**({"CLAUDE_PROJECT_DIR": str(d)} if d else {}))
        r = subprocess.run([posix_sh(), copy.as_posix()], input=b"{}", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, timeout=30)
        out = r.stdout.decode()
        assert r.returncode == 0, (d, r.returncode, r.stderr)
        if warned:
            assert "NOT GUARDED" in json.loads(out)["systemMessage"], (d, out)
        else:
            assert out == "" and r.stderr == b"", (d, out, r.stderr)


CSIDL = {"36": "win", "28": "lad", "38": "pf", "40": "home"}   # the launcher's cygpath -F lookups


def _windows_launcher(tmp):
    """A copy of the launcher that takes its Windows branch, with every known folder a temp dir
    (returned by name), on any OS: the folder search is the launcher's own logic, testable here."""
    text = LAUNCHER.read_text(encoding="utf-8")
    case = "case $(uname -s 2>/dev/null) in"
    assert text.count(case) == 1, "the launcher's Windows test moved"
    text = text.replace(case, "case MINGW64_NT-10.0 in")
    dirs = {}
    for n, name in CSIDL.items():
        call = f"$(cygpath -u -F {n} 2>/dev/null)"
        assert text.count(call) == 1, f"the launcher's {name} lookup moved"
        dirs[name] = tmp / "kf" / name
        dirs[name].mkdir(parents=True)
        text = text.replace(call, f"'{dirs[name].as_posix()}'")
    copy = tmp / "kf" / "launcher.sh"
    copy.write_text(text, newline="\n", encoding="utf-8")
    return copy, dirs


def _fake_python(path, tmp):
    """An executable that records how it was started (POSIX only: Windows runs no #! script)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$0\" \"$@\" \"PY_PYTHON=${{PY_PYTHON-unset}}\" "
                    f"> '{tmp}/ran-python'\nexit 0\n", newline="\n", encoding="utf-8")
    path.chmod(0o755)


def _run_launcher(copy, env):
    return subprocess.run([posix_sh(), copy.as_posix()], input=b"{}", stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=base_env(**env), timeout=30)


def test_windows_launcher_with_no_python_warns_in_a_project_and_is_silent_elsewhere(tmp):
    copy, _dirs = _windows_launcher(tmp)
    proj = tmp / "proj"
    (proj / "_tools" / "eng-tools" / ".git").mkdir(parents=True)
    other = tmp / "other"
    other.mkdir()
    r = _run_launcher(copy, {"CLAUDE_PROJECT_DIR": str(proj)})
    assert r.returncode == 0, (r.returncode, r.stderr)
    msg = json.loads(r.stdout.decode())["systemMessage"]
    assert "NOT GUARDED" in msg and "no Python 3 found" in msg, msg
    r = _run_launcher(copy, {"CLAUDE_PROJECT_DIR": str(other)})
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b""), (r.returncode, r.stdout, r.stderr)


@only_on("posix")
def test_windows_launcher_runs_the_py_launcher_isolated_and_ignores_py_python(tmp):
    copy, dirs = _windows_launcher(tmp)
    _fake_python(dirs["win"] / "py.exe", tmp)
    _fake_python(dirs["lad"] / "Programs" / "Python" / "Python313" / "python.exe", tmp)
    r = _run_launcher(copy, {"PY_PYTHON": "2.7", "CLAUDE_PROJECT_DIR": str(tmp)})
    assert r.returncode == 0, (r.returncode, r.stderr)
    argv = (tmp / "ran-python").read_text(encoding="utf-8").splitlines()
    assert argv[0].endswith("/win/py.exe"), f"the py launcher is tried first: {argv}"
    assert argv[1:3] == ["-3", "-I"] and argv[3].endswith("/engstd_guard.py"), argv
    assert argv[-1] == "PY_PYTHON=unset", f"a session's PY_PYTHON reached the py launcher: {argv}"


@only_on("posix")
def test_windows_launcher_without_py_takes_the_newest_installed_python(tmp):
    copy, dirs = _windows_launcher(tmp)
    for v in ("Python311", "Python313"):
        _fake_python(dirs["lad"] / "Programs" / "Python" / v / "python.exe", tmp)
    r = _run_launcher(copy, {"CLAUDE_PROJECT_DIR": str(tmp)})
    assert r.returncode == 0, (r.returncode, r.stderr)
    argv = (tmp / "ran-python").read_text(encoding="utf-8").splitlines()
    assert "/Python313/python.exe" in argv[0], f"not the newest: {argv}"
    assert argv[1] == "-I" and argv[2].endswith("/engstd_guard.py"), argv


def test_windows_scope_compares_submodule_paths_without_case(tmp):
    """On Windows `_TOOLS/Eng-Tools` is the same folder as `_tools/eng-tools`; a gitlink there
    must keep the session in scope. Elsewhere case is significant, as git's is."""
    shim = _shim_module()
    saved = shim.WINDOWS
    try:
        shim.WINDOWS = True
        assert shim._is_eng_tools_submodule("_TOOLS/Eng-Tools", "")
        assert shim._is_eng_tools_submodule("ECAD/_Tools/ENG-TOOLS", "https://x.invalid/Eng-Tools.git")
        assert not shim._is_eng_tools_submodule("ECAD/_tools/eng-tools", "https://x.invalid/other.git")
        shim.WINDOWS = False
        assert not shim._is_eng_tools_submodule("_TOOLS/Eng-Tools", "")
        assert shim._is_eng_tools_submodule("_tools/eng-tools", "")
    finally:
        shim.WINDOWS = saved


@only_on("nt")
def test_windows_git_and_settings_come_from_known_folders(tmp):
    shim = _shim_module()
    profile = shim.known_folder("Profile")
    assert profile is not None and profile.is_dir(), profile
    found = shim.git_exe()
    assert found is not None and found.name == "git.exe" and found.is_file(), found
    assert shim._settings_file({}) == profile / ".claude" / "settings.json"
    cfg = tmp / "cfg"
    assert shim._settings_file({"CLAUDE_CONFIG_DIR": str(cfg)}) == cfg / "settings.json"
    # HOME (Git Bash sets one of its own) does not move the settings file.
    assert shim._settings_file({"HOME": str(tmp)}) == profile / ".claude" / "settings.json"


def test_the_hook_command_runs_through_the_shell_claude_code_uses(tmp):
    """The hooks.json command itself, as Claude Code runs a shell-form hook (`sh -c`; Git Bash
    on Windows), with ${CLAUDE_PLUGIN_ROOT} given the forward-slash form Claude Code uses."""
    std, proj = guarded(tmp)
    command = GUARD_COMMAND.replace("${CLAUDE_PLUGIN_ROOT}", ROOT.as_posix())
    ev = json.dumps(edit(std / "eng-standards" / "x", proj)).encode()
    r = subprocess.run(native() + hook_shell() + [command], input=ev, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=base_env(PATH=os.environ.get("PATH", ""),
                       HOME=str(tmp / "home"), CLAUDE_PROJECT_DIR=str(proj), **settings_dir(tmp)),
                       timeout=60)
    if WINDOWS and b"no Python 3 found" in r.stdout:
        raise NotChecked("no Python in the folders the Windows launcher searches: " + r.stdout.decode())
    assert r.returncode == 2 and b"blocked by stub guard" in r.stderr, (r.returncode, r.stdout, r.stderr[-400:])


def test_scope_someone_elses_eng_tools_submodule_does_not_count(tmp):
    """Nit 1: a repo with an unrelated `*eng-tools` submodule is not an eng project."""
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    for i, (path, url) in enumerate((("libs/foo-eng-tools", "https://x.invalid/foo-eng-tools.git"),
                                     ("vendor/eng-tools", "https://x.invalid/eng-tools.git"),
                                     ("deps/_tools/eng-tools", "https://x.invalid/other.git"))):
        repo = make_repo(tmp / f"r{i}", "other", path)
        (repo / ".gitmodules").write_text(f'[submodule "{path}"]\n\tpath = {path}\n\turl = {url}\n', encoding="utf-8", newline="\n")
        git(repo, "add", ".gitmodules")
        git(repo, "commit", "-q", "-m", "sub")
        assert_silent_allow(*run_shim(edit(repo / "CLAUDE.md", repo), tmp, repo))


def test_bash_events_go_through_the_guard(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(bash(f'rm "{std / "eng-standards" / "lights.yaml"}"', proj), tmp, proj)
    assert code == 2 and "bash on" in err, (code, err)
    assert_silent_allow(*run_shim(bash("ls", proj), tmp, proj))


def test_config_change_in_a_project_goes_to_the_guard(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(config_change("project_settings", proj), tmp, proj)
    assert code == 2 and "blocked by stub guard" in err, (code, err)


def test_config_change_outside_a_project_is_silent(tmp):
    std = make_std(tmp)
    set_option(tmp, std / "eng-standards")
    other = make_repo(tmp, "elsewhere")
    assert_silent_allow(*run_shim(config_change("user_settings", other), tmp, other))


def test_a_crashing_guard_is_not_turned_into_a_silent_pass(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(edit("CRASH", proj), tmp, proj)
    assert code not in (0, 2), f"crash became exit {code}"
    assert err.strip(), "crash left no message"


def test_unparseable_stdin_is_handed_to_the_guard_unchanged(tmp):
    std, proj = guarded(tmp)
    code, out, err = run_shim(None, tmp, proj, raw=b"not json")
    assert code == 1 and "JSONDecodeError" in err, (code, err)


def test_the_real_guard_through_the_shim(tmp):
    real = ROOT.parent / "eng-standards" / "hooks" / "guard_auditor.py"
    if not real.is_file():
        raise NotChecked(f"no guard_auditor.py at {real}")
    # A copy in a temp <STD> protects that temp folder, because the guard self-locates (ES-052).
    std = make_std(tmp, guard_text=real.read_text(encoding="utf-8"))
    set_option(tmp, std / "eng-standards")
    proj = make_project(tmp)
    code, out, err = run_shim(edit(std / "eng-standards" / "lights.yaml", proj), tmp, proj)
    assert code == 2 and "guard_auditor.py" in err, (code, err)
    assert run_shim(edit(proj / "notes.md", proj), tmp, proj)[0] == 0
    assert run_shim(edit(proj / "_tools" / "eng-tools" / "x.py", proj), tmp, proj)[0] == 2
    code, out, err = run_shim(bash(f'echo x > "{std / "eng-standards" / "lights.yaml"}"', proj), tmp, proj)
    assert code == 2, (code, err)
    assert run_shim(bash(f'cat "{std / "eng-standards" / "lights.yaml"}"', proj), tmp, proj)[0] == 0
    assert run_shim(config_change("project_settings", proj), tmp, proj)[0] == 2
    git(std / "eng-standards", "init", "-q")
    assert_silent_allow(*run_shim(edit(std / "eng-standards" / "lights.yaml", std / "eng-standards"),
                                  tmp, std / "eng-standards"))


def test_where_reports_both_values_and_uses_the_saved_one(tmp):
    std, proj = guarded(tmp)
    fake = make_std(tmp, guard_text=PERMISSIVE_GUARD, name="fake")
    base = base_env(PATH=os.environ.get("PATH", ""), HOME=str(tmp / "home"),
                    ENGSTD_ROOT=str(fake / "eng-standards"), **settings_dir(tmp))
    r = subprocess.run([sys.executable, str(SHIM), "--where", str(proj)], stdout=subprocess.PIPE,
                       timeout=60, env=base)
    out = r.stdout.decode()
    assert r.returncode == 0 and f"eng-standards: {(std / 'eng-standards').resolve()}" in out, out
    assert "(ignored)" in out and str(fake) in out and "eng project: " + str(proj.resolve()) in out, out
    r = subprocess.run([sys.executable, str(SHIM), "--where", str(proj), "--use-env-override"],
                       stdout=subprocess.PIPE, timeout=60, env=base)
    assert f"eng-standards: {(fake / 'eng-standards').resolve()}" in r.stdout.decode(), r.stdout
    (tmp / "home" / ".claude" / "settings.json").unlink()
    r = subprocess.run([sys.executable, str(SHIM), "--where", str(proj)], stdout=subprocess.PIPE,
                       timeout=60, env=base)
    assert r.returncode == 1 and b"NOT FOUND" in r.stdout, r.stdout


def _committed_files():
    # Tracked plus untracked-but-not-ignored: what a commit would publish.
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others",
                        "--exclude-standard"], stdout=subprocess.PIPE)
    if r.returncode == 0 and r.stdout:
        names = [n for n in r.stdout.decode().split("\0") if n]
    else:
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()
                 and ".git" not in p.parts and "__pycache__" not in p.parts]
    return [ROOT / n for n in names if (ROOT / n).is_file()]


HEX64 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def test_no_committed_file_carries_a_64_hex_string(tmp):
    """A SHA-256 beside a skill line confirms the name it replaced (N2). None in git, anywhere."""
    hits = []
    for f in _committed_files():
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if HEX64.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{n}")
    assert not hits, "64-hex strings in committed files: " + ", ".join(hits[:20])


def test_sources_lists_every_skill(tmp):
    src = (ROOT / "SOURCES.md").read_text(encoding="utf-8")
    for s in SKILLS:
        assert f"skills/{s}/SKILL.md" in src and f"`{s}`" in src, s


# ---------------------------------------------------------------- outside this repo

def test_neutrality_scan_has_zero_hits(tmp):
    et = eng_tools_dir()
    checker, deny = et / "check_neutral.py", et / "neutral-denylist.txt"
    if not checker.is_file() or not deny.is_file():
        raise NotChecked(f"no check_neutral.py / neutral-denylist.txt in {et}")
    # Scan exactly what git would publish (tracked and untracked-unignored files), so ignored
    # build litter is not judged and nothing a commit would add escapes. The working copy as a
    # whole must also scan clean; README says so.
    tree = tmp / "published"
    for f in _committed_files():
        dst = tree / f.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    r = subprocess.run([sys.executable, str(checker), f"--root={tree}", f"--denylist={deny}"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    out = r.stdout.decode()
    if r.returncode == 2:
        raise NotChecked("check_neutral.py exited 2: " + out.strip().splitlines()[-1])
    assert r.returncode == 0, out


def test_claude_plugin_validate_passes(tmp):
    exe = shutil.which("claude")
    if not exe:
        raise NotChecked("no `claude` CLI on PATH")
    # The directory form validates only the marketplace; the plugin.json form also loads
    # hooks/hooks.json, skills and commands. --strict turns warnings into failures.
    for target in (ROOT, ROOT / ".claude-plugin" / "plugin.json", ROOT / "skills", ROOT / "commands"):
        r = subprocess.run([exe, "plugin", "validate", "--strict", str(target)], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=120)
        out = r.stdout.decode()
        assert r.returncode == 0 and "Validation passed" in out, out


# Collected after the last test so an added test is never silently skipped.
TESTS = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)
         and os.name in getattr(f, "platforms", (os.name,))]
SLOW = {"test_neutrality_scan_has_zero_hits", "test_claude_plugin_validate_passes"}

MUTANTS = [
    ("scripts/engstd_guard.py", "the shim fails open silently",
     '    print(msg, file=stderr)\n    print(json.dumps({"systemMessage": msg}), file=stdout)\n',
     "    pass\n"),
    ("scripts/engstd_guard.py", "the guard's block is swallowed", "    return r.returncode\n\n\ndef where",
     "    return 0\n\n\ndef where"),
    ("scripts/engstd_guard.py", "a guard crash becomes a silent allow",
     "    if r.returncode not in (0, 2):", "    if r.returncode not in (0, 2):\n        return 0\n    if False:"),
    ("scripts/engstd_guard.py", "the event is not passed to the guard", "input=raw,", 'input=b"{}",'),
    ("scripts/engstd_guard.py", "ENGSTD_ROOT honoured in hook mode",
     "    engstd, notes = locate(env)\n", "    engstd, notes = locate(env, use_env_override=True)\n"),
    ("scripts/engstd_guard.py", "an ignored override is not reported",
     "        if val and (saved_path is None or _resolve(val) != saved_path):", "        if False:"),
    ("scripts/engstd_guard.py", "unrelated repos are guarded",
     "        return 0                                   # not an eng project: not the guard's session",
     "        pass"),
    ("scripts/engstd_guard.py", "the <STD> repos are guarded",
     "        return 0                                   # the owner's own <STD> repos", "        pass"),
    ("scripts/engstd_guard.py", "scope read from the working tree, not HEAD/index",
     '        for args in (["ls-tree", "HEAD", "--", p], ["ls-files", "-s", "--", p]):',
     '        if not (top / p).is_dir():\n            continue\n        for args in (["ls-tree", "HEAD", "--", p], ["ls-files", "-s", "--", p]):'),
    ("scripts/engstd_guard.py", "a folder named _tools/eng-tools counts without a gitlink",
     'any(l.startswith("160000 ")', '(top / p).is_dir() or any(l.startswith("160000 ")'),
    ("scripts/engstd_guard.py", "a bogus CLAUDE_PROJECT_DIR is silent",
     "    if not project_dir or not os.path.isdir(project_dir):", "    if not project_dir:"),
    ("scripts/engstd_guard.py", "the working-tree .gitmodules is not a scope signal",
     '    if _gitmodules_paths(_read_regular(top / ".gitmodules")):', "    if False:"),
    ("scripts/engstd_guard.py", "_tools/eng-tools/.git is not a scope signal",
     "    if (top / DEFAULT_SUB / \".git\").exists():", "    if False:"),
    ("scripts/engstd_guard.py", "a .git that git rejects reads as not a repo",
     "                raise ScopeError(f\"{d / '.git'} exists", "                return None\n                raise ScopeError(f\"{d / '.git'} exists"),
    ("scripts/engstd_guard.py", "git is looked up on the session's PATH",
     '    genv["PATH"] = FIXED_PATH', '    genv.setdefault("PATH", os.defpath)'),
    ("scripts/engstd_guard.sh", "the launcher keeps the session's PATH",
     "PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin\nexport PATH", "export PATH"),
    ("scripts/engstd_guard.sh", "no python3 is silent even in a project",
     '        printf \'%s\\n\' "{\\"systemMessage', '        : \'%s\\n\' "{\\"systemMessage'),
    ("scripts/engstd_guard.sh", "no python3 warns in every repo",
     "    if likely_in_scope; then", "    if true; then"),
    ("scripts/engstd_guard.py", "any submodule whose path ends in eng-tools counts",
     '    return last in ("eng-tools", "eng-tools.git") and path.endswith("/" + DEFAULT_SUB)',
     '    return path.endswith("eng-tools")'),
    ("scripts/engstd_guard.sh", "the launcher lets PYTHON* variables through",
     'exec python3 -I "$(dirname "$0")/engstd_guard.py"', 'exec python3 "$(dirname "$0")/engstd_guard.py"'),
    ("scripts/engstd_guard.py", "the settings file is opened whatever it is",
     "        if not stat.S_ISREG(os.stat(f).st_mode):", "        if False:"),
    ("tests/plugin_checks.py", "missing frontmatter accepted",
     '            problems.append(f"{rel}: no frontmatter")\n            continue\n        for key',
     "            continue\n        for key"),
    ("tests/plugin_checks.py", "a skill without a description accepted",
     'for key in ("name", "description"):', 'for key in ("name",):'),
    ("tests/plugin_checks.py", "a marketplace without an owner accepted",
     '    if not isinstance(owner, dict) or not owner.get("name"):', "    if False:"),
    ("tests/plugin_checks.py", "a plugin.json without a name accepted",
     '        problems.append("plugin.json: `name` is required")', "        pass"),
    ("tests/plugin_checks.py", "a source with .. accepted",
     '            if ".." in src.split("/"):', "            if False:"),
    ("tests/plugin_checks.py", "a hooks file without its wrapper accepted",
     '    if not isinstance(h, dict) or not isinstance(h.get("hooks"), dict):',
     '    if not isinstance(h, dict):\n        return []\n    if "hooks" not in h:\n        h = {"hooks": h}\n    if False:'),
    ("tests/plugin_checks.py", "an unparseable command accepted",
     '            raise FrontmatterError(f"frontmatter line {n} has an unclosed quote")',
     "            pass"),
    ("SOURCES.md", "a source-line hash committed",
     "| `skills/mcad-env/SKILL.md` | `mcad-env` |", "| `skills/mcad-env/SKILL.md` | `mcad-env` | " + "ab" * 32 + " |"),
    ("hooks/hooks.json", "skill reloads blocked by the ConfigChange hook",
     '"matcher": "user_settings|project_settings|local_settings"', '"matcher": "*"'),
    # ES-069: Windows.
    ("hooks/hooks.json", "PowerShell calls are not guarded",
     '"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell"',
     '"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash"'),
    ("hooks/hooks.json", "the launcher is found on the session's PATH",
     '"command": "/bin/sh \\"${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.sh\\"",\n            "timeout": 60\n          }\n        ]\n      }\n    ],\n    "ConfigChange"',
     '"command": "sh \\"${CLAUDE_PLUGIN_ROOT}/scripts/engstd_guard.sh\\"",\n            "timeout": 60\n          }\n        ]\n      }\n    ],\n    "ConfigChange"'),
    ("scripts/engstd_guard.sh", "the Windows launcher lets PY_PYTHON choose the interpreter",
     "unset PY_PYTHON PY_PYTHON3 PYLAUNCHER_ALLOW_INSTALL PYLAUNCHER_ALWAYS_INSTALL\n", "\n"),
    ("scripts/engstd_guard.sh", "the py launcher runs without -I",
     'exec "$py" -3 -I "$(dirname "$0")/engstd_guard.py"', 'exec "$py" -3 "$(dirname "$0")/engstd_guard.py"'),
    ("scripts/engstd_guard.sh", "the Windows launcher takes the oldest Python",
     '[ -f "$py" ] && found=$py', '[ -f "$py" ] && [ -z "$found" ] && found=$py'),
    ("scripts/engstd_guard.sh", "no Windows Python is silent even in a project",
     '        not_guarded "no Python 3 found', '        exit 0; not_guarded "no Python 3 found'),
    ("scripts/engstd_guard.py", "Windows scope compares submodule paths with case",
     "    if WINDOWS:\n        path, last = path.replace", "    if False:\n        path, last = path.replace"),
]


def run_suite(tests, quiet=False):
    failed, unchecked = [], []
    for name, fn in tests:
        with tempfile.TemporaryDirectory(prefix="engstd plugin test ") as d:
            try:
                fn(Path(d).resolve())
                if not quiet:
                    print(f"  pass         {name}")
            except NotChecked as e:
                unchecked.append(name)
                if not quiet:
                    print(f"  NOT CHECKED  {name}: {e}")
            except Exception as e:
                failed.append(name)
                if not quiet:
                    print(f"  FAIL         {name}\n        " + str(e).replace("\n", "\n        "))
                    if not isinstance(e, AssertionError):
                        traceback.print_exc()
    return failed, unchecked


def _tree_clean(paths):
    r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--"] + paths,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode != 0 or not r.stdout.strip()   # not a git checkout: nothing to compare


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-k", help="only tests whose name contains this")
    ap.add_argument("--mutants", action="store_true")
    ap.add_argument("--fast", action="store_true", help="skip the two tests that leave this repo")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    tests = [t for t in TESTS if (not a.k or a.k in t[0]) and not (a.fast and t[0] in SLOW)]
    if not a.quiet:
        print(f"testing the plugin at {ROOT.name}/\n")
    failed, unchecked = run_suite(tests, quiet=a.quiet)
    print(f"\n{len(tests) - len(failed) - len(unchecked)}/{len(tests)} passed, "
          f"{len(failed)} failed, {len(unchecked)} NOT CHECKED")
    if failed or not a.mutants:
        return 1 if failed else (2 if unchecked else 0)
    files = sorted({m[0] for m in MUTANTS})
    if not _tree_clean(files):
        print("refusing to run mutants: uncommitted changes in " + ", ".join(files))
        return 1
    print("\nmutants (each must be caught by at least one test):")
    bad = 0
    for fname, label, old, new in MUTANTS:
        target = ROOT / fname
        src = target.read_text(encoding="utf-8")
        if src.count(old) != 1:
            print(f"  STALE     {label}  (target found {src.count(old)}x)")
            bad += 1
            continue
        try:
            target.write_text(src.replace(old, new), encoding="utf-8", newline="\n")
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--fast", "--quiet"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        finally:
            target.write_text(src, encoding="utf-8", newline="\n")
        if r.returncode == 1:
            print(f"  caught    {label}")
        else:
            print(f"  SURVIVED  {label}  — no test checks this rule")
            bad += 1
    print(f"\n{len(MUTANTS) - bad}/{len(MUTANTS)} mutants caught")
    return 1 if bad else (2 if unchecked else 0)


if __name__ == "__main__":
    sys.exit(main())
