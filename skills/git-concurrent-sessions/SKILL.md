---
name: "git-concurrent-sessions"
description: "Use before staging, committing, or clearing a git lock in any repo another Claude session or the owner may also be working in. Snapshot what is already dirty, commit only your own changes, never sweep another session's work."
---

# Concurrent sessions in one git repo

More than one Claude session can be working in the same repo at the same time, on the same
machine, with no way to see each other. This is the two-copies-no-drift problem at the session
level: git has exactly one index per repo and no idea which session staged what.

**Observed 2026-09-26, in the `beta` and `alpha-hw` repos.** Two commits from another session landed on
top of this session's mid-turn. A `git add` in the second repo left a `.git/index.lock` this
session could not unlink, blocking commits for hours.

**Observed 2026-09-27, and this one caused real damage.** A commit meant to carry a handful of files carried
many more: `git add -- "<project>/ECAD/_tools/mcad-tools"` swept dozens of another session's
uncommitted work into a commit about part numbering. Every staged path matched a declared path,
so the path guard passed. **Path-prefix matching is not enough.** Declaring a directory makes
every foreign change inside it look authorized.

## The five hard rules

1. **Snapshot what is already dirty, and never stage any of it.** Before doing any work, record
   the dirty set for the paths you will touch. Anything modified or untracked in that snapshot
   belongs to someone else. This is the rule that rules 2–3 could not supply.

   ```bash
   git status --porcelain -- <paths> | cut -c4- | sed 's/^"//;s/"$//' > /tmp/foreign.txt
   ```

   Before committing, every staged file must be absent from that list. If one is present, do not
   "fix" the staging — `git reset -q`, and stage by explicit filename instead of by directory.
2. **Explicit paths only.** Never `git add -A`, `git add .`, `git add -u`, or `git commit -a`.
   Prefer naming individual files over naming a directory in any repo that is shared.
3. **Verify the staged set before committing** — against the declared paths *and* against the
   foreign snapshot. If either check fails, `git reset -q` and stop.
4. **Never delete a lock you have not proven is yours.** A `.git/index.lock` may belong to a live
   process mid-write. Prove ownership first: zero bytes, and an mtime matching your own failed
   command. Say so before removing it. On a FUSE-mounted folder, deleting may need a grant, and a
   grant can lapse when the connection resets — which is how these orphans appear.
5. **Verify after committing.** List the files in each commit and confirm every one is yours, then
   report the other session's uncommitted count before and after. A drop larger than your own file
   count means you swept something — say so immediately rather than letting it pass.

## A sync or vendoring tool makes the whole directory foreign

Running a tool that merges or stamps a shared directory (`sync_copies.py`, any vendoring script)
leaves that directory modified far beyond the files you changed: it re-stamps manifests and pulls
in everything the other side had in flight. **Treat its entire output directory as foreign except
the files the tool reports changing**, and stage exactly those by name. Note in the commit message
that a manifest it stamped describes files the commit does not contain.

## Probe for activity before touching the index

```bash
find . -path ./.git -prune -o -type f -newermt '-15 minutes' -print | wc -l
```

Zero means idle. Non-zero means another session or the owner is working; re-probe rather than trusting
an earlier reading. Activity can resume between the probe and the commit, so the probe informs
caution — it never replaces rules 1–5.

## The claim protocol

Before staging, declare the paths you intend to touch so another session can see them. Claims live
in `.git/claude-claims/<session-id>.json`, which git ignores by construction. A claim announces
intent; it does not make the files inside yours — rule 1 still decides that.

```python
import json, os, time, glob
CLAIMS, TTL = ".git/claude-claims", 3600
os.makedirs(CLAIMS, exist_ok=True)
mine, paths = "<session-id>", ["docs/thing.md"]
conflicts = []
for f in glob.glob(f"{CLAIMS}/*.json"):
    if os.path.basename(f) == f"{mine}.json":
        continue
    c = json.load(open(f))
    if time.time() - c["at"] > c.get("ttl", TTL):
        continue                      # expired: the owner went away without releasing
    for p in paths:
        for q in c["paths"]:
            if p == q or p.startswith(q.rstrip("/") + "/") or q.startswith(p.rstrip("/") + "/"):
                conflicts.append((c["session"], q))
if conflicts:
    print("CLAIMED BY ANOTHER SESSION:", conflicts)   # do not stage
else:
    json.dump({"session": mine, "at": time.time(), "ttl": TTL, "paths": paths},
              open(f"{CLAIMS}/{mine}.json", "w"))
```

Release by deleting your claim file once committed. An expired claim is reclaimable — say in the
report that you overrode a stale one and name its session.

## When a path is already claimed

Wait and retry, up to **30 minutes total**. A tool call caps at 180 seconds, so **never sleep
inside the call** — a retry loop with sleeps just times out mid-attempt and leaves you unsure what
landed. Retry across turns or with a scheduled check-in, and read the repo state before each
attempt. At 30 minutes, stop: name the other session, the claimed paths, what is blocked, and
leave the work uncommitted on disk.

## If you did sweep someone else's work

Say so first, before reporting anything you accomplished. Then:

* Do **not** reset or rewrite while the other session is active — that is worse than the mess.
* Check the commit is still recoverable: `HEAD` is still your commit, and nothing is pushed
  (`git branch -r --contains HEAD` is empty). If another commit landed on top, stop and ask.
* Wait for idle, then `git reset --soft HEAD~1`, `git reset` to unstage everything, and re-stage
  only your own files by name before committing again. The foreign files return to being working
  tree modifications, exactly as they were.
* Get the person's go-ahead before rewriting history they may have built on.

## Enforcement status

**Advisory.** A `pre-commit` hook would enforce this on every session in the repo, including ones
that declare no claim — it would start refusing their commits. Ship the hook only once the
protocol has run clean for a while, and say so before turning it on.

## Report line

Close any turn that committed with: which commits you made, how many files in each, that every
path was yours *and* absent from the foreign snapshot, the other session's uncommitted count
before and after, and any claim you overrode or lock you cleared.