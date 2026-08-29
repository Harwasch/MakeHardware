---
name: hw-retro
description: Capture what went badly during hardware work and turn it into specific proposed edits to the MakeHardware toolbox. Use when a task took far more iterations than it should have, when the human corrects or overrules the agent, and at the end of a project or a milestone.
---

# Retrospective

The toolbox only improves if friction gets written down while it is still
fresh and specific. This skill has two granularities, and the cheap one matters
more than the ceremonial one.

## 1. The friction log — during the work

Append to `docs/design/friction-log.md` **in the session it happens**, when any
of these occur:

* the human corrects or overrules a choice you made
* something took markedly more loops than it should have
* you had to guess because information was missing
* a tool behaved differently than the skill said it would
* the human sounds frustrated, or repeats themselves
* **a review came back with changes** — what you built was not what they
  wanted, and the reason is the most useful sentence in the log
* **you got a long way without asking anyone** — if a stage finished with no
  review requested, that is a finding about the workflow, not just about you

One entry, three lines, no ceremony:

```markdown
## 2026-08-28 · E2 schematic capture
**Friction:** Picked a JST-PH connector; human wanted Molex PicoBlade. Third
time connectors have been relitigated across projects.
**Cost:** ~20 min and a re-layout of the board edge.
**Where it belongs:** skills/hw-sourcing/references/connectors.md — the
board-to-wire row is still a TBD placeholder.
```

That third line is the one that matters. **An observation without a named file
is not actionable.** If you genuinely cannot name a file, say so — that itself
is a finding, and it usually means the toolbox has no home for that kind of
knowledge yet.

Do not log ordinary iteration. Design is iterative; two passes at a value is
work, not friction. Log the loops that a better instruction would have avoided.

## 2. The project retro — at a milestone or at the end

Run `/hw-retro`. It reads the friction log, the plan (how estimates compared to
reality), the git history, and the requirements that moved, then writes
`docs/design/retro.md`.

Structure it as **evidence → proposed change**, never as sentiment:

```markdown
# Retro — Thermal Probe

## What worked
- Vision board with two concepts settled the form factor in one session.
  Keep.

## What cost time
### Connector choice was relitigated three times
**Evidence:** friction log 2026-08-28, 2026-09-02; commits a1b2c3, d4e5f6.
**Cost:** roughly one session.
**Proposed change:** fill in the board-to-wire row of
`skills/hw-sourcing/references/connectors.md` with Molex PicoBlade, and add
the reason (crimp tooling already owned).

### Plan underestimated PCB layout by 2 sessions
**Evidence:** E3 estimated 2, took 4.
**Proposed change:** `skills/hw-planning/SKILL.md` — note that layout chunks
on boards with a fixed enclosure envelope typically need double the estimate.

## What to leave alone
- The requirements gate caught two unverified leaves before fab. No change.
```

## Closing the loop

The retro lives in the *project* repo, but the changes it proposes are to
**MakeHardware**. Do not leave it there to rot:

1. Write `docs/design/retro.md` and commit it.
2. Offer to file the proposed changes as a GitHub issue on
   `Harwasch/MakeHardware`, one issue per proposed change, each naming the
   file and the edit. Ask first — the human may want to batch or reword them.
3. If the human is working in the MakeHardware repo itself, offer to make the
   edits directly instead.

## Be honest about your own performance

The point of this is not to produce a document that says things went well.
Name the places where you guessed, where you were wrong, and where the human
had to push back twice. Those are the entries with the most value in them, and
you are the only one who can see them all.

If nothing went badly, say that in a sentence and stop. A padded retro is worse
than a short one, because it dilutes the entries that matter.
