---
name: "refresh-program-board"
description: "Refresh the hardware program board — eng-standards/board/projects/<slug>/state.md — against the project registers, re-audit, and rebuild the one dashboard. Use when asked to refresh, update or check the board."
---

# Refresh the hardware program board

The board is the **intent layer**: one `state.md` per project under
`<STD>/eng-standards/board/projects/<slug>/` (if present: `board/` is private to the owner's clone), typed by a person. It is
a rollup of the project registers, so it drifts. This makes it match again and
says plainly what moved.

Since 2026-09-29 (eng-standards ES-031, ES-033) there is **one dashboard**, rendered by
eng-standards from the auditor's status records *and* the board. The old `pm`
repo, its `refresh.py`, `build_dashboard.py` and `_derived.json` no longer exist; nothing
here derives DRC/ERC counts or git state — that is the auditor's job.

## 1. See where the board stands

```bash
cd "<STD>/eng-standards" && python3 audit.py && python3 dashboard.py
```

`audit.py` writes one status record per project into `status/`; the `program` block of
each record carries the board's claimed gate (`gate_claimed:` in `state.md`) beside the
gate the files support, and L-G8 is red when they disagree. `dashboard.py` renders
`dashboard.html`, with a "Program board" section per slug. Read that section before
touching anything. Use the absolute `mcad` interpreter
(`<mcad python>`, see the `mcad-env` skill) when `python3` is not 3.11.

## 2. Re-read the registers, update `state.md`

For each project the user names, or whose L-G8 disagrees, open the authoritative sources
and update `board/projects/<slug>/state.md` to match:

- The register: `<board>/docs/*_TODO.md` — item statuses, the recommended order.
- The decisions: `<board>/docs/decisions.md`, plus the `alpha-hw` repo's `docs/decisions.md`
  for cross-board ones (K-numbers).
- The auditor's record: `eng-standards/status/<PROJECT>.json` — what the files support.

Take **next actions from the register's own recommended order**. Do not invent a parallel
ordering — the register is the source of truth, `state.md` is a view of it. Reference items
by number; never copy an item's body into the rollup.

Keep the three object types separate and honest:

- **Next actions** — work that can start now. A task blocked on an open question is not an action.
- **Waiting on** — fired at the world, with sent and expected-back dates.
- **Open questions** — each tagged with what it blocks and the cost of being wrong.

Two rules about the claim:

- `gate_claimed:` is the owner's claim. Change it only when the register supports it, and
  say so. **Never type the derived gate into `state.md`**: the auditor derives it and the
  page shows both so a disagreement is seen, not overwritten.
- `health:` is typed and is shown as typed, never as a light. Nothing in `board/` is evidence.

Append a `log.md` entry for the session. Decisions go beside the board, not in `board/`.

## 3. Rebuild and commit

```bash
cd "<STD>/eng-standards" && python3 audit.py && python3 dashboard.py && python3 run_tests.py
```

Then stage **by explicit filename** — `board/projects/<slug>/state.md`, `log.md`, the
`status/*.json` that changed, `dashboard.html` — and commit in eng-standards with a message
naming what actually moved. `board/` is edited only on the owner's instruction (ES-033); a
refresh the owner asked for is that instruction. Push only if the owner said to.

## 4. Report

Lead with what changed and what it means, not with the fact that a refresh ran. Call out
any project whose claim the files do not support (L-G8 red), anything that appeared for the
first time, and anything a number alone would hide.

## Things that have already gone wrong here

- **A rollup that re-derived evidence drifted from the auditor.** pm's `refresh.py` once
  summed ERC counts itself and got the key wrong for most of a day. Evidence is read from
  `status/*.json` only; if a count looks wrong, the fix is in eng-standards' adapters, with
  a test that fails without it.
- **A check is not evidence until it has reported a known-bad input as bad.** A green
  result from an unvalidated reader is worse than no check: it stops anyone looking.
- **Never blanket-silence a check** — no-connect flags applied in bulk, warnings demoted
  without a reason recorded. Demotions get written down as decisions.
- **Don't commit the user's in-progress work.** Other sessions are live in `alpha-hw`
  and `beta`; stage explicit paths, never by directory. Their uncommitted files are
  theirs to commit.
- **Never delete a `.git/index.lock` you have not proven is yours** — zero bytes and an
  mtime matching your own failed command, and say so first.
