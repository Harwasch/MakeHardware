---
name: hw-planning
description: Turn an agreed vision into an engineering project plan of session-sized work chunks with explicit dependencies, then keep it current and render it as a dependency Gantt chart. Use after the vision is agreed and before requirements are written, when asked what to work on next, or whenever a chunk changes status.
---

# Planning

The plan is the second agreement with the human, after the vision. It answers
"what work exists, in what order, and who needs what first" — before anyone
argues about a resistor value.

It lives in `plan.yaml` at the project root and renders into the README.

## Altitude

**One chunk ≈ one AI session.** That is the unit. A chunk should be something
you could hand to a fresh session and get back a reviewable result.

Too small: "add decoupling caps to U3". Too big: "design the electronics".
About right: "power architecture and part selection", "schematic capture and
ERC", "enclosure envelope and internal layout".

Aim for 6–20 chunks on a first plan. If you have 40, you are writing tasks, not
chunks. If you have 3, you are writing headings.

## Pick the disciplines the project actually has

Not every project has every discipline. A machined bracket has `mechanical`
and nothing else; a sensor node has `mechanical`, `electrical`, `firmware` and
`test`. Ask, then set `disciplines:` to only what applies. An empty firmware
lane on a project with no firmware is noise that makes the chart lie.

Common set: `mechanical`, `electrical`, `firmware`, `software`, `test`,
`manufacturing`, `documentation`.

## Dependencies are the point

The ordering is what makes this a plan rather than a list. Be honest about
them: `depends_on` is "cannot start without", not "would be nicer after".

The renderer schedules by longest path, so the critical path falls out of the
data. If everything depends on everything, the chart will say so and you have
learned something.

Watch for the two that catch people out:

* **Mechanical and electrical converge.** PCB outline needs the enclosure;
  the enclosure needs the connector positions. Whichever way you resolve it,
  make it explicit rather than circular — usually "envelope first, detail
  after", with the board outline frozen as an interface.
* **Long-lead parts.** If a part has a 12-week lead time, the chunk that picks
  it is on the critical path whether or not the chart knows about calendar
  time. Say so in the chunk's notes.

## Working the plan

```bash
plan-render --check      # cycles, dangling deps, done-on-unfinished. Exit 1 if broken.
plan-render --summary    # status, what is ready to start, what is awaiting review
plan-render              # write docs/plan.{svg,md,drawio} and the README block
```

Update `status` as work completes and **re-render in the same session**, so the
README always reflects reality. A stale plan is worse than no plan, because
people trust it.

### `done` is checked, not taken on trust

Statuses drift optimistic — chunks get marked `done` while the layout is
unrouted, no fabrication output exists and no simulation has been run — and a
renderer that draws whatever it is told cannot catch that. So `--check` fails
a chunk that claims to be finished when:

* one of its **`depends_on`** chunks is not finished;
* one of its declared **`outputs`** is not on disk (an empty directory counts
  as missing — an empty `sim/thermal/` is not a thermal analysis);
* it declares a **`review`** that is not signed off, or that went stale
  because an agreed artefact changed underneath it.

Declare both. `outputs` is what makes the status checkable; `review` is what
makes it agreed:

```yaml
  - id: E1B
    title: Electrical block diagram and power budget
    status: todo
    depends_on: [E1]
    review: architecture          # must be approved before this can be done
    outputs: [hw/block-diagram.yaml, docs/design/block-diagram.svg]
```

Do not delete an output or a review to make the check pass. That is the same
move as marking a requirement `Verified` to clear the gate.

## This is a checkpoint, not a formality

Put the rendered plan in front of the human and get agreement **before**
starting design work. Three things you are really asking:

1. **Is this all the work?** Missing chunks are cheap now and expensive later.
   Test, documentation and manufacturing are the ones people forget.
2. **Is the order right?** The human often knows a constraint you do not — a
   part they already have, a supplier lead time, a review they must pass.
3. **Is any chunk the wrong size?** One chunk is about one session. A chunk
   that is really three is a plan that will be wrong by a week.

`plan-render` writes two things for this, because they answer different
questions and change at different rates:

| File | What it is |
|---|---|
| `docs/plan.svg` | the dependency Gantt, with status and the critical path outlined — renders inline on GitHub |
| `docs/plan.md` | the **scope**: every chunk's description, dependencies, estimate and outputs, deliberately with **no statuses** |
| `docs/plan.drawio` | the same graph, draggable, for the conversation about a wrong dependency |

Review over `docs/plan.md` and reference the rest. That is what lets the plan
review survive a week of ordinary progress — status changes several times a
session and must not invalidate an agreement — while a real change of scope
makes it stale immediately, which is exactly right.

```bash
plan-render
git add docs/plan.md docs/plan.svg docs/plan.drawio plan.yaml README.md
git commit && git push

review-gate open plan --title "Project plan" \
    --summary "<how many chunks, what the critical path is, what you are unsure about>" \
    --artifact docs/plan.md \
    --reference docs/plan.svg --reference docs/plan.drawio --reference plan.yaml \
    --question "Is this all the work?" \
    --question "Is the order right — do you know a constraint we do not?"
```

Then ask directly with the link (see `hw-review`), block on the answer, and
record it:

```bash
review-gate sign plan --approve --by <name> --note "<what they said>"
```

When a chunk turns out to be two chunks, split it, re-render, and re-open the
review if the scope moved. That is the plan working, not the plan failing.
