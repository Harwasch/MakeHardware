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
plan_render.py --check      # cycles, dangling deps, done-on-unfinished. Exit 1 if broken.
plan_render.py --summary    # status, and what is ready to start now
plan_render.py              # write docs/plan.svg and update the README block
```

Update `status` as work completes and **re-render in the same session**, so the
README always reflects reality. A stale plan is worse than no plan, because
people trust it.

`--check` also catches a chunk marked `done` whose dependencies are not — the
bookkeeping error that quietly makes a status report wrong.

## This is a checkpoint, not a formality

Put the rendered plan in front of the human and get agreement before starting
design work. Two things you are really asking:

1. **Is this all the work?** Missing chunks are cheap now and expensive later.
   Test, documentation and manufacturing are the ones people forget.
2. **Is the order right?** The human often knows a constraint you do not — a
   part they already have, a supplier lead time, a review they must pass.

When a chunk turns out to be two chunks, split it and re-render. That is the
plan working, not the plan failing.
