# eng-claude — the engineering standards as a Claude Code plugin (ES-060)

One install gives a Claude Code session what the standards expect it to have: the five skills,
the eng-standards guard hook, and four commands that run the standards' own scripts. The plugin
carries no rule of its own. The rules live in `eng-standards` and in `eng-tools` (pinned in
each project as `_tools/eng-tools`); the plugin points at them and runs them.

`<STD>` below is the folder holding `eng-tools` and `eng-standards` side by side. "The owner" is
the person who runs the standards.

## What it carries

| part | where | what |
|---|---|---|
| skills | `skills/<name>/SKILL.md` | `ecad-design-document`, `mechanical-engineering-standard`, `mcad-env`, `git-concurrent-sessions`, `refresh-program-board` — maintained here (`SOURCES.md`); migrated on 2026-10-02 from the owner's skills with names, products and machine paths replaced ("the owner", the repo codenames `alpha-hw` / `beta`, `<STD>`, `<mcad python>`) and one project's rules or one machine's facts dropped |
| guard hook | `hooks/hooks.json` → `scripts/engstd_guard.py` | in eng project sessions, PreToolUse on `Edit\|Write\|MultiEdit\|NotebookEdit\|Bash` and ConfigChange on settings changes run `<STD>/eng-standards/hooks/guard_auditor.py` (ES-040) |
| `/engstd:eng-init` | `commands/eng-init.md` | `eng-tools/bin/init_project.py` — always `--dry-run` first; the real run (which writes `CLAUDE.md` and `.claude/settings.json`) only on a yes |
| `/engstd:eng-pin-bump` | `commands/eng-pin-bump.md` | `eng-tools/bin/pin_bump.py` — `--dry-run`, then one `--commit` run on a yes; push is a plain `git push` on a separate yes |
| `/engstd:eng-audit` | `commands/eng-audit.md` | the pinned `check_standard.py`, `check_sch.py --all`, `check_register.py`; every row PASS / FAIL / MISSING / WARN / n/a, MISSING never counted as passing |
| `/engstd:eng-onboard` | `commands/eng-onboard.md` | `eng-tools/ONBOARDING.md` Part 1 and the machine checks (Python ≥ 3.11 + PyYAML, `kicad-cli`, both repos side by side, this plugin, the guard location) |

Plugin commands are namespaced by the plugin name, so `/eng-init` is `/engstd:eng-init`.

### The guard hook

**When it runs.** Only in an eng project session: the repo holding `CLAUDE_PROJECT_DIR`
(where the session started) shows an eng-tools submodule in **any** of four places — a gitlink
(mode 160000) at HEAD, a gitlink in the index (at `_tools/eng-tools`, or at a `.../_tools/eng-tools` path that
`.gitmodules` gives with a URL whose last segment is `eng-tools` or `eng-tools.git`), the
working-tree `.gitmodules` naming such an entry, or a
`_tools/eng-tools/.git` — and the repo is not one of the `<STD>` repos (`eng-standards`,
`eng-tools`). No single slip clears all four: moving `_tools`, `git reset`,
`git rm -r --cached .` and `git read-tree --empty` each leave the session in scope. Everywhere
else — unrelated repos, folders that are not repos, the owner's own sessions in `<STD>` — the
hook exits 0 and prints nothing. The per-call working directory is never used.
`CLAUDE_PROJECT_DIR` unset or not a directory, or a `.git` that git rejects, is a visible
warning.
ConfigChange is hooked for `user_settings`, `project_settings` and `local_settings` only, so
skill reloads are not blocked.

**Where the guard is: one place.** The plugin's **`engstd_root`** option, as saved in
`pluginConfigs` in the user settings file (`~/.claude/settings.json`). Set it once to your
eng-standards clone: Claude Code asks for plugin options when the plugin is enabled, and
`/plugin` or `/config` changes it later. Project settings cannot set `pluginConfigs`.

Project settings *can* put any variable into the hook's environment through their `env` block,
so in hook mode the shim never takes the location from `ENGSTD_ROOT` or
`CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT`. If either is set and differs from the saved option, the hook
says so in a `systemMessage` and uses the saved option. `ENGSTD_ROOT` is honoured only by
`--where --use-env-override`, for tests and diagnosis. The shim does not read an `eng.toml`, a
stub `guard_auditor.py` near the session, its working directory or a submodule URL. The hook
runs through `scripts/engstd_guard.sh`, which resets `PATH` to
`/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin`, unsets `PYTHONPATH`,
`PYTHONHOME`, `PYTHONSTARTUP` and `PYTHONUSERBASE`, and starts `python3 -I`; the shim runs `git`
on that fixed `PATH` and the guard with `-I`.

**What can still move it.** The location comes from the user settings file. Anything that
replaces `python3` or `git` in the fixed `PATH` folders, edits that settings file, or edits this
plugin's own files when it is loaded in place from a clone can still redirect or disable the
guard. These take deliberate steps, not a slip:
the guard is a guard against drift and mistakes, not a sandbox.
With the option unset or wrong, a project session is told it is **NOT GUARDED** on every call
(a `systemMessage` plus stderr) and the call is allowed. A guard that crashes keeps its
non-zero exit (a hook error notice). The settings file is read only when it is a regular file.

`python3 scripts/engstd_guard.py --where [DIR]` prints the saved option, any ignored environment
value, whether DIR is an eng project, and the eng-standards and eng-tools a session there would
use; the commands use it so they never guess a path.

## Install

Nothing installs without the user's go-ahead (below).

**From a git remote** hosting this repo:

```bash
claude plugin marketplace add <owner>/eng-claude          # or the repo's git URL
claude plugin install engstd@engstd-marketplace
```

The repo is private, so git on your machine must already hold a credential: Claude Code runs
git non-interactively and has no token of its own. For HTTPS, `gh auth login` then
`gh auth setup-git`; for SSH, a key loaded in `ssh-agent` with github.com in `known_hosts`
(`owner/repo` tries SSH first; `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` skips it).

**From a local clone:** `claude plugin marketplace add "<STD>/eng-claude"`, then the same
install. A plugin from a marketplace added as a local directory **loads in place**: every
session reads the clone's current files and `version` is ignored. For one session only,
without installing: `claude --plugin-dir "<STD>/eng-claude"`.

**Then point it at the guard:** set the `engstd_root` option to `<STD>/eng-standards` when
asked (or in `/plugin` → the plugin → configure), and check with `/engstd:eng-onboard`.

Requirements: `python3` on the launcher's fixed PATH (`/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin`)
for the hook; the shim is standard library and behaves the same on 3.9 and later, and the guard
needs only the standard library. On a Mac without the Command Line Tools, `/usr/bin/python3` is
the `xcrun` stub, which may prompt to install them. With no `python3` there at all, the hook
allows the call and, in what looks like an eng project, says **NOT GUARDED** in a
`systemMessage`; elsewhere it stays silent. The commands need what
the scripts they run need: Python ≥ 3.11 + PyYAML for eng-tools, `kicad-cli` for boards, the
mcad env (`mcad-env` skill) for mechanical checks.

### What the guard lets the commands do

The eng-standards guard lets a project session run `init_project.py`, `pin_bump.py` and the
checkers from eng-tools, but refuses `pin_bump.py --commit` and `--push` in every form: moving a
pin is the owner's commit. So `/eng-pin-bump` dry-runs the move and then hands the user the exact
`!`-prefixed command to commit it themselves.

## Ask first, every time

Every command repeats this list, and it holds for the whole plugin:

* `git commit` or `git push`
* creating or changing a remote
* installing anything — packages, envs, plugins
* editing any file outside the repo being worked on
* installing or changing hooks or settings
* deleting anything
* running anything fetched from the web

Approval is scoped to what was approved: a yes to a dry run is not a yes to the real run, and a
yes to commit is not a yes to push.

## Update

Background auto-update is **off** for this marketplace by default: turn it on per user in
`/plugin` → Marketplaces → the marketplace → Enable auto-update. Otherwise
`claude plugin update engstd@engstd-marketplace` (restart to apply) or
`/plugin marketplace update engstd-marketplace`. A cached install only receives a release
whose `version` (in `.claude-plugin/plugin.json`) changed, so change it in every release and
add a `CHANGELOG.md` entry. A local-clone install ignores `version` and always loads the
clone's files.

**The skills live here.** This repo is the single source of the five skills (`SOURCES.md`):
they were migrated from the owner's synced skills on 2026-10-02 and are edited here from now on;
nothing regenerates them. **For the owner: edit the skills in this repo, keep them neutral (no
names, products, machine paths or one project's facts), and run the tests — `check_neutral.py`
and the 64-hex test still check every committed file.** **When you enable this plugin, retire
your own synced copies of the five skills:** both would load, under different prefixes.

## Tests

```bash
python3 tests/test_plugin.py            # the suite
python3 tests/test_plugin.py --mutants  # also: every mutant must be caught (needs a clean tree)
```

They check the manifests, hooks file, skill and command frontmatter (`tests/plugin_checks.py`,
each check first made to fail on a known-bad copy); the shim's scope from committed state
(project, subfolder, `.gitmodules` path, staged submodule, unrelated repo, non-repo folder, the
`<STD>` repos) and its guard location (the saved option), with the known-bad cases that must be
caught: `_tools` moved without a commit, `cd` out of the project, a bogus `CLAUDE_PROJECT_DIR`,
`ENGSTD_ROOT` / `CLAUDE_PLUGIN_OPTION_ENGSTD_ROOT` from project settings, a local submodule URL,
a FIFO in place of the settings file, and the `eng.toml` / cwd-stub bypass — against a stub guard
and a temp copy of the real one, for Edit, Bash and ConfigChange events. Also: the launcher with no `python3`; someone else's
`*eng-tools` submodule staying out of scope; the commands' flags against the scripts' `--help`;
no 64-hex string in any committed file; `claude plugin validate --strict`; and the neutrality
scan (`<STD>/eng-tools/check_neutral.py` with its hashed denylist, over the files git would
publish). Tests whose input is absent — eng-tools (`ENGTOOLS_ROOT`,
`ENGTOOLS_BIN`), the real guard, the `claude` CLI — print NOT CHECKED, never pass. The working
copy as a whole also scans clean with `check_neutral.py --root=<this repo>`.

## Format sources

Every format decision follows the Claude Code docs, read on 2026-10-02:

| decision | doc |
|---|---|
| manifest at `.claude-plugin/plugin.json`; `name` the only required field, kebab-case; `version` pins users; skills, commands, hooks at the plugin root, not in `.claude-plugin/`; `${CLAUDE_PLUGIN_ROOT}`; a name with `claude` as a whole word draws a validator warning, hence `engstd` | https://code.claude.com/docs/en/plugins-reference |
| `skills/<name>/SKILL.md`, `commands/<file>.md` → `/<plugin>:<file>`, command files take skill frontmatter; `hooks/hooks.json` under a top-level `"hooks"` key | https://code.claude.com/docs/en/plugins/components |
| `.claude-plugin/marketplace.json`: `name`, `owner.name`, `plugins[]` with `name` + `source`; relative source starts with `./`, resolved from the marketplace root; entry name equals the plugin.json name; `claude plugin marketplace add <owner>/<repo>` | https://code.claude.com/docs/en/plugin-marketplaces and https://code.claude.com/docs/en/plugins/marketplace-reference |
| `userConfig` option of type `directory`, exported to hook processes as `CLAUDE_PLUGIN_OPTION_<KEY>`; `pluginConfigs` read from user (not project) settings | https://code.claude.com/docs/en/plugins-reference and https://code.claude.com/docs/en/settings-reference |
| private-repo auth (`gh auth login` + `gh auth setup-git`, or SSH), auto-update off by default, `version` ignored for a local-directory marketplace | https://code.claude.com/docs/en/plugins/host-marketplace |
| PreToolUse stdin (`tool_name`, `tool_input`, `cwd`, `hook_event_name`), ConfigChange (`source`, matcher values `user_settings` / `project_settings` / `local_settings` / `policy_settings` / `skills`, blockable by exit 2), `CLAUDE_PROJECT_DIR` exported to hooks, exit 0 / 2 / other, matcher `A\|B`, exec form (`command` + `args`, no shell, so a path with spaces stays one argument), `systemMessage` shown to the user | https://code.claude.com/docs/en/hooks |
| frontmatter (`description`, `argument-hint`, `disable-model-invocation`), `$ARGUMENTS`, `${CLAUDE_PLUGIN_ROOT}` substituted in command content | https://code.claude.com/docs/en/slash-commands (now the skills page) |

The docs call `commands/` the older format and prefer skills for new work; the four commands
are kept as `commands/*.md` because the brief asks for slash-command files, and they set
`disable-model-invocation: true` so only the user starts them.
