"""Structural checks for this plugin, per the Claude Code docs cited in README.md.

Each `check_*` returns a list of problems (strings); an empty list is clean. They read files
only. `tests/test_plugin.py` proves each one flags a known-bad input before it trusts its
verdict on the real tree.

What is required, and where the requirement comes from:

* `.claude-plugin/plugin.json` - `name` is the only required key, kebab-case; component
  paths start with `./` (plugins-reference: Fields, Path rules).
* `.claude-plugin/marketplace.json` - `name`, `owner` (with `owner.name`) and `plugins` are
  required; each entry needs `name` and `source`; a relative source starts with `./` (or is
  `.`) and never contains `..` (plugins/marketplace-reference: Top-level fields, Plugin
  entries, Relative path plugin source).
* `hooks/hooks.json` - the event map sits under a top-level `"hooks"` key; a file without
  that wrapper fails to load (plugins-reference: hooks). Each handler of type `command` has
  a `command`; `args`, when present, is a list of strings (hooks: command hook fields).
* `skills/<name>/SKILL.md` - YAML frontmatter; this plugin also requires `name` (equal to
  the folder) and `description` on every skill (the brief; docs: description "recommended").
* `commands/*.md` - frontmatter that parses, with a `description`.
"""
import json
import re
from pathlib import Path

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ID_CHARS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMPONENT_KEYS = ("skills", "commands", "agents", "hooks", "mcpServers", "lspServers",
                  "outputStyles", "workflows")


class FrontmatterError(ValueError):
    pass


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_frontmatter(text):
    """The frontmatter mapping, or None when the file has none. Raises FrontmatterError when
    it is there but does not parse."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        raise FrontmatterError("frontmatter opened with --- and never closed")
    block = text[4:end]
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            raise FrontmatterError(f"frontmatter is not YAML: {e}")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise FrontmatterError("frontmatter is not a mapping")
        return data
    data = {}
    for n, line in enumerate(block.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            raise FrontmatterError(f"frontmatter line {n} is not `key: value`: {line!r}")
        val = m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif val[:1] in "\"'":
            raise FrontmatterError(f"frontmatter line {n} has an unclosed quote")
        data[m.group(1)] = val
    return data


def _rel_path_ok(p):
    return isinstance(p, str) and p.startswith("./") and ".." not in Path(p).parts


def check_plugin_manifest(root):
    root = Path(root)
    f = root / ".claude-plugin" / "plugin.json"
    if not f.is_file():
        return [f"{f}: missing"]
    try:
        m = load_json(f)
    except ValueError as e:
        return [f"{f}: not JSON: {e}"]
    if not isinstance(m, dict):
        return [f"{f}: not a JSON object"]
    problems = []
    name = m.get("name")
    if not isinstance(name, str) or not name:
        problems.append("plugin.json: `name` is required")
    elif not KEBAB.match(name):
        problems.append(f"plugin.json: `name` {name!r} is not kebab-case")
    for key in ("version", "description"):
        if key in m and not isinstance(m[key], str):
            problems.append(f"plugin.json: `{key}` must be a string")
    if "author" in m and not (isinstance(m["author"], dict) and m["author"].get("name")):
        problems.append("plugin.json: `author` needs a `name`")
    for key in COMPONENT_KEYS:
        if key not in m:
            continue
        vals = m[key] if isinstance(m[key], list) else [m[key]]
        for v in vals:
            if isinstance(v, str) and not (_rel_path_ok(v) or (key == "skills" and v == ".")):
                problems.append(f"plugin.json: `{key}` path {v!r} must start with ./ and stay inside")
            elif isinstance(v, str) and not (root / v).exists():
                problems.append(f"plugin.json: `{key}` path {v!r} does not exist")
    return problems


def check_marketplace(root):
    root = Path(root)
    f = root / ".claude-plugin" / "marketplace.json"
    if not f.is_file():
        return [f"{f}: missing"]
    try:
        m = load_json(f)
    except ValueError as e:
        return [f"{f}: not JSON: {e}"]
    if not isinstance(m, dict):
        return [f"{f}: not a JSON object"]
    problems = []
    name = m.get("name")
    if not isinstance(name, str) or not ID_CHARS.match(name or "") or ".." in (name or ""):
        problems.append("marketplace.json: `name` is required (letters, digits, . _ -)")
    owner = m.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        problems.append("marketplace.json: `owner` with `owner.name` is required")
    plugins = m.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        problems.append("marketplace.json: `plugins` must be a non-empty array")
        plugins = []
    seen = set()
    for i, e in enumerate(plugins):
        if not isinstance(e, dict):
            problems.append(f"marketplace.json: plugins[{i}] is not an object")
            continue
        en = e.get("name")
        if not isinstance(en, str) or not ID_CHARS.match(en or ""):
            problems.append(f"marketplace.json: plugins[{i}] needs a valid `name`")
        if en in seen:
            problems.append(f"marketplace.json: duplicate plugin name {en!r}")
        seen.add(en)
        src = e.get("source")
        if src is None:
            problems.append(f"marketplace.json: plugins[{i}] needs a `source`")
        elif isinstance(src, str):
            if ".." in src.split("/"):
                problems.append(f"marketplace.json: plugins[{i}].source {src!r} contains ..")
            elif not (src == "." or src.startswith("./")):
                problems.append(f"marketplace.json: plugins[{i}].source {src!r} must start with ./")
            elif not (root / src).is_dir():
                problems.append(f"marketplace.json: plugins[{i}].source {src!r} is not a directory")
            else:
                pj = root / src / ".claude-plugin" / "plugin.json"
                if pj.is_file():
                    try:
                        pname = load_json(pj).get("name")
                    except ValueError:
                        pname = None
                    if pname != en:
                        problems.append(f"marketplace.json: plugins[{i}] name {en!r} differs from "
                                        f"plugin.json name {pname!r}")
        elif not (isinstance(src, dict) and src.get("source")):
            problems.append(f"marketplace.json: plugins[{i}].source is neither a path nor a source object")
    return problems


def check_hooks(root):
    root = Path(root)
    f = root / "hooks" / "hooks.json"
    if not f.is_file():
        return []
    try:
        h = load_json(f)
    except ValueError as e:
        return [f"{f}: not JSON: {e}"]
    if not isinstance(h, dict) or not isinstance(h.get("hooks"), dict):
        return ["hooks.json: the event map must sit under a top-level \"hooks\" key"]
    problems = []
    for event, groups in h["hooks"].items():
        if not isinstance(groups, list):
            problems.append(f"hooks.json: {event} must be an array of matcher groups")
            continue
        for gi, g in enumerate(groups):
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list) or not g["hooks"]:
                problems.append(f"hooks.json: {event}[{gi}] needs a non-empty `hooks` array")
                continue
            if "matcher" in g and not isinstance(g["matcher"], str):
                problems.append(f"hooks.json: {event}[{gi}].matcher must be a string")
            for hi, hd in enumerate(g["hooks"]):
                where = f"hooks.json: {event}[{gi}].hooks[{hi}]"
                if not isinstance(hd, dict) or hd.get("type") != "command":
                    problems.append(f"{where}: only `type: command` handlers are expected here")
                    continue
                if not isinstance(hd.get("command"), str) or not hd["command"]:
                    problems.append(f"{where}: `command` is required")
                args = hd.get("args")
                if args is not None and not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
                    problems.append(f"{where}: `args` must be a list of strings")
                for a in [hd.get("command") or ""] + list(args or []):
                    if "${CLAUDE_PLUGIN_ROOT}/" in a:
                        target = root / a.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].strip("\"'")
                        if not target.exists():
                            problems.append(f"{where}: {a!r} names a file that does not exist")
    return problems


def check_skills(root):
    root = Path(root)
    problems = []
    skills = sorted((root / "skills").glob("*/SKILL.md")) if (root / "skills").is_dir() else []
    for f in skills:
        rel = f.relative_to(root)
        try:
            fm = parse_frontmatter(f.read_text(encoding="utf-8"))
        except FrontmatterError as e:
            problems.append(f"{rel}: {e}")
            continue
        if fm is None:
            problems.append(f"{rel}: no frontmatter")
            continue
        for key in ("name", "description"):
            if not isinstance(fm.get(key), str) or not fm.get(key).strip():
                problems.append(f"{rel}: frontmatter `{key}` is required")
        if isinstance(fm.get("name"), str) and fm["name"] != f.parent.name:
            problems.append(f"{rel}: `name` {fm['name']!r} differs from its folder {f.parent.name!r}")
    return problems


def check_commands(root):
    root = Path(root)
    problems = []
    cmds = sorted((root / "commands").glob("*.md")) if (root / "commands").is_dir() else []
    for f in cmds:
        rel = f.relative_to(root)
        try:
            fm = parse_frontmatter(f.read_text(encoding="utf-8"))
        except FrontmatterError as e:
            problems.append(f"{rel}: {e}")
            continue
        if fm is None:
            problems.append(f"{rel}: no frontmatter")
            continue
        if not isinstance(fm.get("description"), str) or not fm["description"].strip():
            problems.append(f"{rel}: frontmatter `description` is required")
    return problems


def check_all(root):
    out = []
    for fn in (check_plugin_manifest, check_marketplace, check_hooks, check_skills, check_commands):
        out += fn(root)
    return out


if __name__ == "__main__":
    import sys
    probs = check_all(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
    for p in probs:
        print(p)
    print(f"{len(probs)} problem(s)")
    sys.exit(1 if probs else 0)
