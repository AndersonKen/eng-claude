---
name: "ecad-design-document"
description: "Use when the owner asks Claude to own an ECAD/PCBA board design end to end, or to produce a design document report for a board (new or existing)."
---

# Owning an ECAD board

The reference standard is the reference board's v1 design document (the owner names it; if present). Its authority comes from one property: **every number has a source.** The report's shape is easy to imitate and worth nothing on its own. Earn the numbers first; the shape follows.

The document is a build output, not a writing task. A doc regenerated from the netlist cannot drift from the board.

The rules live in the ECAD standard. This skill is the workflow around them; where the two disagree, the standard wins and this skill is the bug.

## 0. Before any design decision

Read, in order, and report what each contained — or that you looked and it was absent, naming the path either way:

1. The ECAD standard, from the repo's pinned eng-tools submodule (one copy; never a vendored or repo-local `STANDARD.md`):
   - every project repo: `_tools/eng-tools/ecad-tools/STANDARD.md`, under the repo's ECAD subfolder where it keeps its boards there (`<subfolder>/_tools/eng-tools/ecad-tools/STANDARD.md`)

   Most process questions are already decided there.
2. `<board>/docs/<BOARD>_TODO.md` — open work, numbered. **The design task is usually already written here.** Do not invent scope.
3. `<board>/docs/<BOARD>_REQUIREMENTS.md` — the S1 table from previous sessions. Amend it; never regenerate it.
4. `<board>/docs/decisions.md` and the repo-root `docs/decisions.md` (`K` numbers) — they explain why things are as they are.
5. `<board>/docs/<BOARD>_design.yml` — the board's declarations the checkers read (`rails:`, `reserved:`, `ffc:`, `interfaces:`, `waivers:`, `silk:`, `layers:`, `high_speed:`, `switch_nodes:`).
6. `<board>/docs/ARTIFACTS.md` — work published as artifacts, not files.
7. `python3 "<STD>/eng-standards/ecad_gate.py" status <board>` — which E gate the board is at.

`pm/` is a rollup, never a source.

Never call something missing, broken, clean or done without naming the scope checked in the same sentence: "I searched `<path>` for `<thing>` and found nothing" — not "there is no X". A narrow negative means widen, not conclude.

If the S1 output is mostly novel rather than recovered from these files, say so — it means either the board's records are thin or the read did not happen.

## 1. Requirements gate (S1 = gate E0) — never skipped, and it has a pass test

The design is bounded by requirements supplied, not requirements inferred.

The output is `<board>/docs/<BOARD>_REQUIREMENTS.md`: a table with **stable row numbers** (R1, R2…), amended across sessions and never regenerated, so completeness ratchets instead of resetting. Append-only in the same spirit as `decisions.md` — supersede a row, do not silently rewrite it.

| column | content |
|---|---|
| `R#` | stable, permanent |
| requirement | the thing being fixed |
| value | the value, or `N/A — <why>` |
| tag | one of the six in section 2 |
| source | the document, instrument or conversation |
| class | `BLOCK` / `RETRIM` / `BRINGUP` (below) |
| owner | `the owner` / `datasheet <which>` / `measurement <of what, with what>` / `supplier <which>` |

**Classify every unknown. Only one class gates the next stage.**

- **BLOCK** — a wrong answer invalidates work that cannot be cheaply redone: mating interface, connector orientation, supply rail, MCU choice, board outline. Anything that moves copper you would have to re-route.
- **RETRIM** — proceed now; being wrong costs a value change at one or two references. **Name the references.** (The reference board's `C1c` trim position is the model: the unknown was parked at a designator and the board still went to fab.)
- **BRINGUP** — not knowable until hardware exists. Goes straight to the section-8 open-items table and blocks nothing.

Rows required — a blank is a defect; `N/A — <why>` is a valid value:

- the one sentence this board exists to satisfy
- supply: source, range, quiescent, peak, what browns out first
- interfaces: each connector, its mate, and the document that fixes the pinout
- outline, keepouts, height budget — each with its source
- environment: temp, ingress, vibration, CAN/marine
- manufacturing: layer count (JLCPCB 4/6/8 by default; anything else is a decision), assembly side, part class, board quantity
- firmware contract: what the other side already expects

**S1 passes when every row has a value and a tag, and no `BLOCK` row is `[ASSUMED]` or `[n/c]`.** This is the E0 rule as the gate reads it. An empty unknown list is *not* required and is *not* the goal — the reference board shipped with eleven open items. Every `[ASSUMED]` or `[n/c]` `BLOCK` row must have an owner; no orphans.

An S1 returned as complete at full confidence is a warning sign, not a success: it means either the board has no engineering left in it, or `[ASSUMED]` rows were rounded into plain numbers to clear the gate. Report the honest shape instead.

An open question is admissible only if it names where it was already looked for — the standard, the TODO, `decisions.md`, the supplied datasheets. A question answerable from material already in hand is a defect, not diligence.

Datasheets: any part whose datasheet is not in hand → propose the part, do not design against a remembered pinout.

Report at S1: the table, the `BLOCK` rows that need the owner, and the diff against the previous S1 if one exists. Nothing else. Then stop — do not proceed to S2 unprompted.

## 2. Provenance rule

Every number in the design and the report carries one tag. These are the six the E0 gate accepts:

| tag | means |
|---|---|
| `[ds]` | datasheet in hand, with document, table or section, and the text as printed |
| `[meas]` | a measurement — what measured it, when |
| `[calc]` | a calculation — the script and function, the formula's source, inputs themselves tagged; the value comes from a `facts/` file |
| `[stated]` | stated by the owner — when, and where it is recorded |
| `[ASSUMED]` | a design choice Claude made — with the consequence of being wrong and how to check it. **Never a recalled datasheet value or typical.** |
| `[n/c]` | not computed: the value would need a number not in hand. Name the document it needs. |

A value you would otherwise fill from memory is `[n/c]`, not `[ASSUMED]` (STANDARD §7: a recalled typical is not an input). `[ASSUMED]` and `[n/c]` both block a `BLOCK` row.

An untagged number is a defect. Twenty `[ASSUMED]` or `[n/c]` lines beat one smooth paragraph. If the work isn't done, the section says so. The reference document's `source` column and its "not measured yet" admissions are why it is trustworthy.

The tag *is* the per-row confidence. Never report a confidence percentage over a table — it is a `min()` across every row and says nothing about where the softness is.

## 3. Staged review, and the E gates

| stage | work | E gate it serves |
|---|---|---|
| S1 | requirements | E0 Requirements |
| S2 | architecture: block diagram, power chain, pin map | (feeds E1) |
| S3 | schematic + calculations | E1 Schematic, E2 Schematic reviewed (long-lead parts ordered here) |
| S4 | placement + stackup, pre-route | (feeds E3) |
| S5 | routed board, gate output, BOM with stock | E3 Layout, E4 DFM + sourcing |
| S6 | document | — |
| — | release; boards received | E5 Released to fab, E6 Boards received |

The gate conditions are in eng-standards `gates.yaml`; read them there, not here. Gate records go through `python3 "<STD>/eng-standards/ecad_gate.py" pass|reopen <board> <gate>`:

- A pass needs its conditions met and needs **no** decision. A pass recorded from a Claude session is a **claim** until the owner runs `ecad_gate.py confirm` from their own terminal. Report it as a claim.
- A reopen needs a decision first, naming why frozen content changed.

Each stage carries the S1 discipline forward: new unknowns are classified `BLOCK` / `RETRIM` / `BRINGUP` and appended to the requirements table with new `R#` numbers. `BLOCK` stops the stage; the other two are recorded and the work continues.

At each stage: what was done, what was assumed, **one alternative considered and why it lost**, and what would prove it wrong. The owner wants disagreement — take a position and defend it. Call out any request that skips or reorders this sequence.

The owner works from diagrams, not prose: lead each stage with the drawing or render and call out changes on it.

## 4. Gates — report the command and its raw output, not a verdict

Run the checkers; do not re-decide what they decide. `bin/check_standard.py <board-dir>` is the audit; the others are its parts (all under `_tools/eng-tools/ecad-tools/bin/`):

| checker | standard |
|---|---|
| `check_sch.py` — the schematic thresholds | §9 |
| `check_pins.py`, `check_passives.py` — against `parts/<MPN>.yml` (an IC with no declaration is MISSING, or an open item naming the datasheet) | §3, §4 |
| `check_bom.py` — newest `fab/` release against the design | §4 |
| `check_figures.py` — every image names its generator | §7 |
| `check_interface.py` — mating pairs, net by net | §3 |
| `check_silk.py` | §7 |

Counting traps that have produced false clean results here:

- **ERC 0.** Violations nest under `sheets[]`; `erc.json["violations"]` is empty even when the board is not.
- **DRC 0 violations and 0 unconnected.** `unconnected_items` is its own array, outside `violations`.
- DRC runs against **JLCPCB's rules** (§5), pinned beside the snapshot, with zones refilled first. A run against KiCad defaults proves nothing about the fab.
- Every differential pair has a `diff_pair_uncoupled` and `diff_pair_gap` rule in the `.kicad_dru` (§2). Without one, DRC says nothing about the pair.
- Snapshots taken across a design-rule change are not comparable. A rule change gets its own commit naming the rule and both values.
- Every fitted BOM line has a stocked LCSC code, with stock count and date checked (`jlc_lookup.py`). Extended stock moves — rerun before ordering.
- A checker is not evidence until it has failed on a known-bad input. Make it fail on purpose first.
- Verify the thing — file changed, count differs, HEAD moved — not exit 0.

## 5. Everything regenerates

Nothing hand-drawn, nothing hand-calculated. Each step is a committed script with a `tests/test_<name>.py`, whose output is committed under `docs/`, styled from `ecadkit/theme.py`:

Find the board's own script for each stage before writing one. Reuse one from another board where it exists. A stage with no script on this board is an open item in `<BOARD>_TODO.md`; never do it by hand.

- Every calculated number is written by `ecadkit.facts.write(...)` to `docs/design_doc/facts/<name>.json`, with the `selftest=` record from `ecadkit.selftest.ensure()`. The document generator reads it from there; nothing is retyped from stdout.
- Section 7 of the report lists each script and what it produces.
- Schematic and board edits go through KiCad, never text edits to `.kicad_sch`.
- A generator that prints to stdout leaves no artifact — the repo cannot see it.

## 6. House conventions — check every new design against these

These are declared in `<BOARD>_design.yml` so a checker reads them; a convention that only lives here is not enforced.

- Board-to-board FFC/cable pinouts are **palindromic** (GND, VBUS, D+, D−, D−, D+, VBUS, GND) so a flipped cable is still correct. Where the conductor count makes that impossible, spend the symmetry on the supplies so a flip is non-working rather than destructive. List the connector under `ffc:`.
- The KiCad project is the source of truth for every board; read an EAGLE schematic only where no KiCad project exists.
- Never commit without the owner's go-ahead. When the owner approves one, stage explicit paths only and never sweep the owner's in-progress work (`git-concurrent-sessions`).
- Reference register items by number; never copy a body into a rollup. Decisions are append-only and permanently numbered — supersede, never rewrite.

## 7. Report structure

Title + one-line what-it-is + document date + repo paths; **What this is**; **Status** (board / before ordering / firmware, one line each, plus the E gate from `ecad_gate.py status`, claims marked as claims); Contents. Then:

1. **Background** — the chain this board sits in, why it exists, and a **constraints table with a `source` column**
2. **Architecture** — power chain, operating concept, pin map table
3. **The PCB** — stack and rules (the JLCPCB stackup code, cited), placement figures, circuit-block table, the calculations with their acceptance windows plotted (a window without a source is not drawn)
4. **Parts and availability** — full BOM: value, package, LCSC code, basic/extended, stock, fitted/DNP, date checked
5. *(Mechanical — only when there is mechanical work)*
6. **What the firmware has to do**
7. **How the design is generated and regenerated** — script/output table, with each calculator's test command and raw output
8. **Open items, risks and next steps** — required, never empty; columns: item / why it matters / what to do. Every `RETRIM` and `BRINGUP` row from the requirements table lands here, by `R#`.
- **Appendices** — connector pinout, file index

Include the mistake the work caught, if it caught one. In the reference document that paragraph is the most credible thing in it.

## 8. Credit economy

The owner pays for this. Push heavy search — placement, routing, optimization sweeps — to local scripts on the owner's machine rather than hand-solving in context. Prefer building a reusable generator over a one-off answer, and record any new lesson that reduces credit use in `claude/workflow-credit-economy.md` (if present).
