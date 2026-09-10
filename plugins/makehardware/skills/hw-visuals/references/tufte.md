# Why the charts look like this

Edward Tufte's four books are the source; the rules below are the ones that
actually change a hardware review, with what each one costs when it is broken.
They are worth knowing rather than just following, because the interesting
cases are the ones no rule covers.

## Above all else, show the data

The purpose of a graphic is comparison, and every mark that is not a comparison
is a mark competing with one. Before drawing anything, name the comparison in
one sentence: *38.2 µA against a 40 µA budget*. If you cannot, you have a table,
not a chart, and a table is fine — a chart of one number is worse than the
number.

## Maximise the data-ink ratio; erase non-data ink

Tufte's definition: data-ink is the ink that would be lost if a data point were
removed. Everything else is decoration. The practical edits:

* **Drop the frame.** A box around a plot encodes nothing.
* **Drop the gridlines**, or make them so faint the eye passes over them. A
  reader who needs a precise value needs a number, not a grid.
* **Drop the legend** and label the line where it ends.
* **Drop the axis you are not using.** Three round ticks beats eleven.
* **Never a 3D bar, ever.** The third dimension carries no data and distorts the
  two that do.

The test is subtractive: remove an element and ask whether anything was lost.
Usually not.

## Chartjunk

Moiré patterns, hatched fills, heavy grids, gradients, drop shadows,
self-promoting graphics. Every one of them adds visual noise that the reader has
to filter before reaching the data. In an engineering review the cost is
specific: a reviewer who is decoding your chart is not checking your circuit.

## Small multiples

Sequences of the same small graphic, sharing scale and design, differing only
in the data. Once the reader has learned to read one panel they can read all of
them, and the comparison becomes visual rather than arithmetic.

This is the right form for **corner sweeps**, and it is why `hw-chart corners`
forces one scale per measurement. Six panels with six auto-scaled y-axes is six
charts pretending to be a comparison; the one thing they make impossible is the
comparison they were drawn for.

## Sparklines

Word-sized, intense, simple graphics — a data-ink ratio of essentially 1.0, no
axes, no frame, no ticks. In a hardware document they belong inline in a table:
a rail's current over a startup transient, in the row about that rail, right
beside its number.

The rule that makes them work: **a sparkline needs its endpoint value printed
next to it.** The shape shows the behaviour, the number gives the magnitude, and
neither alone is enough.

## Layering and separation

Different kinds of information at different visual weights, so the eye separates
them without being told. In these charts:

* Data at full weight.
* The limit, the spec line, the budget outline at half weight and dashed —
  present, and clearly not data.
* Axes and labels at the lightest weight that is still readable.

A spec line drawn as heavily as the measurement makes the reader work out which
is which every time they look.

## Micro/macro readings

A good graphic reads at two distances. From across the room the reviewer sees
*one bar is red*; up close they see *41.7 µA against a 40 µA limit at 85 °C and
3.0 V*. Both readings should be true and neither should need the other.

This is why every value goes in a `<title>` as well as on the chart: the macro
reading is the picture, the micro reading is one hover away, and neither is
allowed to crowd the other off the page.

## The lie factor

Size of the effect shown in the graphic, divided by the size of the effect in
the data. It should be 1.

The two ways it stops being 1 in engineering charts:

* **A truncated axis.** A bar chart whose y-axis starts at 38 makes a 4%
  difference look like a factor of three. Bars start at zero. Line plots may be
  truncated, because a line encodes position rather than length — but say so.
* **Area used to encode a single quantity.** Doubling a circle's radius
  quadruples its area, so the reader sees 4x for a 2x change.

## Colour

Colour carries meaning here, and only three of them do:

* **Red — failing, over budget, no evidence.** Never used for anything else.
* **Amber — close to the limit.** The one worth watching.
* **Green — passing.**

Series colours are a separate, deliberately quieter set, because a series is
identity and not status.

Two constraints on all of it: **state is never colour alone** — a failing bar is
red *and* carries a marker *and* its number, so it survives a mono print and a
colour-blind reader — and **every palette is checked in both light and dark**,
because the review page follows the reader's theme and half of them read in
dark.

## Where Tufte does not settle it

* **Interaction.** The books predate it. A hover value is not chartjunk: it is
  the micro reading, hidden until asked for, which is exactly what layering is
  for. The rule that carries over is that the chart must be complete without it,
  because a printed page and a screenshot have no hover.
* **Annotation.** Tufte is sparing; an engineering review should not be. The
  failing corner gets a callout with a sentence, because the reader's job is to
  decide, not to discover.
* **Redundancy.** Strict data-ink says a bar labelled with its own value is
  redundant. In a review it is not: the number is what gets quoted into an
  email, a requirement or a fab note, and it must be exactly right rather than
  read off a pixel.
