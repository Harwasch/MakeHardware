# Which plot, for which decision

A chart earns its place by changing what somebody does. Every entry below names
the decision first, because if there is no decision, the chart is decoration and
a sentence would be better.

---

## The budget bar — *is any rail close to its limit?*

`hw-chart budget rails.csv`

One row per rail or per consumer, drawn as a filled bar inside the outline of
its budget. The reviewer never does arithmetic: the fraction is the picture.

The single most useful thing in an architecture review is *a rail at 95% of its
limit*, and it is invisible in a block diagram. Put this beside the diagram and
the review has something to be about.

Amber past 85%, red past 100% with the overage named, and the worst row
annotated whether or not it fails — because that is the row the conversation is
going to be about.

## The corner small-multiple — *does it still meet spec at the corners?*

`hw-chart corners corners.csv`

One panel per measurement, one bar per corner, **one shared scale per panel**,
the spec drawn as a dashed line, failures in red with a marker and their value
in bold.

`hw-verification` is explicit that evidence at nominal is not evidence. This is
the shape that shows corner evidence honestly: a nominal-only result has one bar
and looks obviously thin, which is the point.

Lead the summary with the corner that fails. Never with the average.

## Bode with the margins marked — *is the loop stable, and by how much?*

`hw-chart bode ac.csv`

Gain and phase against log frequency, with the crossover, phase margin and gain
margin **computed from the data** and annotated on it. Nothing is typed in: a
margin typed into a caption is a margin that stopped being true at the next
simulation.

Under 45 degrees of phase margin the annotation turns red and says so. That is
usually the whole review.

## The annotated trace — *what does it actually do over time?*

`hw-chart trace tran.csv --mark "x=1.2e-3,label=regulator enable"`

Series direct-labelled at the end of the line, events marked where they happen.
Use it for startup, for a load step, for an inrush, for a shutdown.

A transient plot with no annotation is a picture of a squiggle. The annotation
is the content: *this is where the rail comes up*, *this is the overshoot*,
*this is where the brownout detector would trip*.

## The coverage bar — *what is left to verify?*

`hw-chart coverage coverage.csv`

Gaps drawn **first**, then partial, then verified. That ordering is deliberate
and it matches the house rule: lead with gaps, not percentages. "Firmware has
eleven requirements with no evidence" starts a conversation; "62% coverage" ends
one.

## The waterfall — *where did the cost, the power or the mass go?*

`hw-chart waterfall bom.csv`

Contributions biggest first, accumulating to a total. Almost always the top two
items are the entire story, and a waterfall is the shape that shows that in one
look. A pie chart is the shape that hides it.

Same tool for BOM cost, for a current budget by consumer, and for a mass budget.

## The stackup cross-section — *does every signal layer have a return path?*

`hw-chart stackup stackup.csv`

Layers top to bottom, compressed so 35 µm of copper is still visible next to
1.1 mm of core, with the real micrometre figure printed beside each. A signal
layer with no adjacent reference plane is called out in red.

`hw-review/references/exports.md` says a layout review needs the stackup as a
table. This is that table, in a form where a missing reference plane is visible
rather than deducible.

---

## The ones with their own tools

| Question | Tool |
|---|---|
| What is the architecture? | `block-diagram` — draw.io plus SVG, both generated |
| What is the plan, what is next, what is blocked? | `plan-render` — dependency Gantt |
| Where do the requirements come from and what realises them? | `req-trace --map` |
| What is wrong with this schematic sheet? | `sch-lint --svg` |
| What is wrong with this board? | `pcb-lint --svg` |
| What does the part look like, and does it fit? | `cad-export` — render, section, exploded |
| What will the board look like? | `kicad-cli pcb render`, both sides |

Use the tool rather than drawing the picture yourself. Each one reads from the
file that owns the data, so it is right on the next run.

---

## Shapes to avoid, and what to use instead

| Instead of | Use | Because |
|---|---|---|
| A pie chart | a waterfall or a sorted bar | Angles cannot be compared; lengths can |
| A dual-axis chart | two stacked panels sharing an x-axis | Two y-axes let the author imply any correlation they like |
| A table of ten numbers | a bar chart with the numbers on the bars | You get the comparison *and* keep the exact values |
| A table of two numbers | a sentence | A chart of two numbers is slower to read than the numbers |
| A stacked bar of five categories | small multiples | Only the bottom segment shares a baseline; the rest cannot be compared |
| A rainbow colour map | a single-hue ramp | Rainbow invents boundaries where the data has none |
| A screenshot of a plot window | the SVG | It cannot be zoomed, themed, hovered, or diffed |

## Before publishing any of it

* **Look at it yourself.** Render it, open it, read it as a stranger would. Half
  of what a reviewer would catch, you will catch first.
* **Check it in both themes.** The review page follows the reader's, and about
  half read in dark.
* **`review-artifact --check`**, which exits 1 and names anything the page could
  not embed. Much cheaper than finding out from the human.
