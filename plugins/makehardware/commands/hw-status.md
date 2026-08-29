---
description: Report project status - plan progress, requirements coverage, and what is ready to work on next
---

Give the human an honest status report on this project. Run all three, and
report what they say rather than a summary impression:

1. **Reviews** — `review-gate list`. This goes first because it is the one
   that blocks other people rather than you.
2. **Plan** — `plan-render --summary`, then `plan-render` to refresh
   `docs/plan.{svg,md,drawio}` and the README block so the chart is not stale.
   `plan-render --check` for `done` chunks whose outputs or reviews are
   missing.
3. **Requirements** — `req-trace` for coverage and gaps, and `req-trace --map`
   to refresh the requirements map.
4. **Architecture** — if `hw/block-diagram.yaml` exists, `block-diagram
   --summary` for the power budget, and `block-diagram` to refresh the diagram
   and the review image if the spec is newer than them.
5. **Design checks** — if a KiCad project exists, `kicad-cli sch erc` and
   `kicad-cli pcb drc` against the *current* files.

Then report, in this order:

* **What the human owes an answer on** — every review that is `requested` or
  `stale`, with the github.com link. A stale review is the urgent one: they
  agreed to something and it has since changed underneath them.
* **What is blocked**, and on what.
* **What is ready to start now** — chunks whose dependencies are all done.
* **Requirements coverage**, as the number the gate prints. If it is 60%, say
  60%.
* **Any rail over or near its budget**, with the largest contributors. A rail
  at 95% is worth saying out loud even though the gate passes.
* **What changed** since the last report, if you can tell.

Commit the refreshed artefacts. A status report whose chart is a week old is
worse than none.

Lead with gaps, not with the percentage complete. Do not describe the project
as on track while the gate is failing, a chunk is blocked, or a milestone
review is unsigned — name the blocker and what it would take to clear it. A
stage whose review has never been requested is not done, however much of its
work is finished.
