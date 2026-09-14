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
**MakeHardware**. Do not leave it there to rot.

### What counts as a system finding

The test is mechanical: **the edit changes a file in the plugin.** A finding
qualifies if you can name a path under `skills/`, `scripts/`, `references/`,
`templates/` or `env/` and say what it should say instead.

Not this: "the motor housing conducts 35% more heat through the bearing
carrier than we modelled." True, expensive, and about *this design* — it
belongs in an ADR. The system finding hiding next to it is "the thermal
skill never prompts for conduction through mounting hardware", and that one
names `skills/hw-magnetics/SKILL.md`.

### Record first, publish second

```bash
hw-feedback new --file skills/hw-sourcing/references/connectors.md \
    --title "Connector choice is relitigated every project" \
    --edit "Fill in the board-to-wire row with Molex PicoBlade, and say why" \
    --evidence "friction log 2026-08-28, 2026-09-02; commits a1b2c3, d4e5f6" \
    --cost "about one session" --kind "Missing guidance"
```

The friction log's third line — *where it belongs* — is exactly what
`--file` takes, so entries feed the tool directly.

This writes `docs/design/feedback/<date>-<slug>.md` in **this** repo and
commits with the work. It needs no network, no GitHub account and no
credentials, which is the point: the finding is cheapest to capture at the
moment it happens, and that moment is never one where somebody wants to open
a browser.

Then, at the retro:

1. Write `docs/design/retro.md` and commit it, along with the records.
2. Run `hw-feedback publish`. It prepares one issue for the batch and prints
   a link, a dedup search, and the body to paste.
3. **The human files it.** Unless the session happens to have a working `gh`
   channel to the plugin's repo, `hw-feedback` cannot — a cloud session's
   token is scoped to this project repo. It will say `NOT FILED`.
4. When they tell you the issue URL, `hw-feedback mark <slug> <url>` so the
   record knows where it went. A record whose `published:` stays empty
   forever is a finding that did not make it.

**Never report a prepared issue as filed.** "I've filed the issue" when what
exists is a URL is the most likely way this goes wrong, and it is the kind of
wrong nobody catches until they go looking for an issue that was never there.
Say "prepared", give the link, and wait.

If the human is working in the MakeHardware repo itself, offer to make the
edits directly instead — the record is still worth writing, because it is the
evidence the edit rests on.

## Be honest about your own performance

The point of this is not to produce a document that says things went well.
Name the places where you guessed, where you were wrong, and where the human
had to push back twice. Those are the entries with the most value in them, and
you are the only one who can see them all.

If nothing went badly, say that in a sentence and stop. A padded retro is worse
than a short one, because it dilutes the entries that matter.
