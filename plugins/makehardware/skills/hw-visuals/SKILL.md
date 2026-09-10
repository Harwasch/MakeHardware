---
name: hw-visuals
description: Make the deliverable a picture rather than a wall of text - which chart answers which review question, how to draw one that survives Tufte's rules, and hw-chart, which generates them from the file that owns the numbers. Use whenever a result, a budget, a sweep, a coverage report or a comparison is about to be written as a paragraph or a table, when building anything for a review page, and when asked for a plot, a chart, a summary or a presentation.
---

# The picture is the deliverable

A hardware review is a set of numbers with a decision attached. Handed forty of
them as a table, a reviewer skims. The same forty in the right picture answer
the question in one second — *which rail is closest to its limit*, *which corner
fails*, *how much phase margin is left* — and that is the entire job of the
document.

So the default is inverted from how it usually goes:

> **If a number can be plotted, plot it. If a comparison can be drawn, draw it.
> Prose is for the thing the picture cannot say — why it matters and what you
> want the human to decide.**

Three or four sentences of text around a chart is a review. Fifteen paragraphs
with a render at the top is a document nobody finishes.

```bash
hw-chart budget    rails.csv     --out docs/design/power-budget.svg
hw-chart corners   corners.csv   --out docs/design/standby-corners.svg
hw-chart bode      ac.csv        --out docs/design/loop-gain.svg
hw-chart trace     tran.csv      --out docs/design/startup.svg
hw-chart coverage  coverage.csv  --out docs/design/coverage.svg
hw-chart waterfall bom.csv       --out docs/design/cost.svg
hw-chart stackup   stackup.csv   --out docs/design/stackup.svg

hw-chart <kind> --schema        # exactly what columns it wants
```

Every one is a themed SVG of two to seven kilobytes and under a hundred
elements, so it inlines on the review page, renders on github.com, stays crisp
at any zoom, follows the reader's light or dark theme, and puts the exact value
one hover away in a `<title>`.

## Which chart answers which question

| The question a reviewer is actually asking | Chart |
|---|---|
| *Is any rail close to its limit?* | `budget` — bars inside their budget outline, worst annotated |
| *Does it still meet spec at the corners?* | `corners` — small multiples on one scale, spec line drawn, failure marked |
| *Is the loop stable, and by how much?* | `bode` — margins computed from the data and annotated |
| *What does it do over time?* | `trace` — series direct-labelled, events marked |
| *What is left to verify?* | `coverage` — gaps first, then partial, then verified |
| *Where did the cost / the power / the mass go?* | `waterfall` — biggest first, running total |
| *Does every signal layer have a return path?* | `stackup` — the cross-section, unreferenced layers flagged |
| *What is the architecture?* | `block-diagram` (its own tool) |
| *What is the plan and what is next?* | `plan-render` (its own tool) |
| *Where are the requirements and how do they connect?* | `req-trace --map` |
| *What does the board or the schematic look like, and what is wrong with it?* | `sch-lint --svg`, `pcb-lint --svg` |
| *What does the part look like, and does it fit?* | `cad-export` renders, section and exploded view |

If none of those fits, read `references/engineering-plots.md` before inventing
one, and `references/tufte.md` before drawing it.

## The rules every chart here follows

1. **Direct labelling, never a legend.** A legend makes the reader hold a
   colour in their head and walk back and forth between key and data. Put the
   name at the end of the line.
2. **Show the limit, and the distance to it.** A bar chart of current draw says
   nothing. The same bars inside their budget say everything, and the reviewer
   never has to do arithmetic.
3. **Annotate the anomaly.** The failing corner gets the callout. If nothing is
   annotated, the reader has to find the story themselves, and they will not.
4. **No chartjunk.** No 3D, no gradients, no drop shadows, no frame, no
   gridlines the eye trips over. Ink that is not data is ink working against
   data.
5. **Small multiples share one scale.** Six panels with six y-axes is six
   charts. Six panels on one scale is a comparison, which is what was wanted.
6. **State is never colour alone.** A failing bar is red *and* carries its
   number *and* a marker, so it survives a mono print and a colour-blind
   reader.
7. **Generated, not typed.** Every number comes from the file that owns it. A
   figure typed into markdown is already wrong; it just does not know yet.

`references/tufte.md` is where these come from and why they hold.

## Where the picture goes

Both surfaces, and they are not the same surface:

* **The repository** gets committed SVG and PNG, because that is what the human
  still has tomorrow and what renders on github.com. `.stl` too, for anything
  3D — it is the only 3D format GitHub shows in an interactive viewer.
* **The review page** (`review-artifact`) is where the interaction lives:
  pan-and-zoom on every diagram, an orbitable 3D model, hoverable values,
  sortable tables. That is the artefact to lead the review request with.

`hw-review/references/exports.md` has the byte budgets and the recipes. The one
to remember: **prefer SVG for anything that is line art** — a schematic, a plot,
a diagram, a drawing. It inlines, it themes, it has no meaningful size limit.
Reserve rasters for what is genuinely photographic.

## Writing around the picture

Three or four sentences, in this order:

1. What this is, and what changed since they last saw it.
2. **The number or the choice you want confirmed** — the one the chart is about.
3. What you are least sure about.
4. What happens next if they say yes.

Lead with the gap, not the percentage. "Firmware has eleven requirements with
no evidence" is a review; "62% coverage" is a number that ends the
conversation.
