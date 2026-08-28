---
description: Report project status - plan progress, requirements coverage, and what is ready to work on next
---

Give the human an honest status report on this project. Run all three, and
report what they say rather than a summary impression:

1. **Plan** — `plan_render.py --summary`, then `plan_render.py` to refresh
   `docs/plan.svg` and the README block so the chart is not stale.
2. **Requirements** — `req_trace.py` for coverage and gaps.
3. **Architecture** — if `hw/block-diagram.yaml` exists, `block-diagram
   --summary` for the power budget, and `block-diagram` to refresh the diagram
   and the review image if the spec is newer than them.
4. **Design checks** — if a KiCad project exists, `kicad-cli sch erc` and
   `kicad-cli pcb drc` against the *current* files.

Then report, in this order:

* **What is blocked**, and on what.
* **What is ready to start now** — chunks whose dependencies are all done.
* **Requirements coverage**, as the number the gate prints. If it is 60%, say
  60%.
* **Any rail over or near its budget**, with the largest contributors. A rail
  at 95% is worth saying out loud even though the gate passes.
* **What changed** since the last report, if you can tell.

Lead with gaps, not with the percentage complete. Do not describe the project
as on track while the gate is failing or a chunk is blocked — name the blocker
and what it would take to clear it.
