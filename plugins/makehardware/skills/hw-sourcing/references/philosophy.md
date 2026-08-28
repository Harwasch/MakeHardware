# How to decide

House philosophy for component selection. Edit freely; this is meant to change.

## Boring parts, interesting products

Prefer the part that is widely used, widely stocked, and well documented over
the part that is optimal on a datasheet line. Novelty in a component is risk
you carry for the life of the product, and it buys nothing the customer sees.

Reach for the interesting part only when a requirement genuinely demands it,
and when you do, say so in the ADR.

## Two sources or a written reason

A part with a single source needs an explicit decision, not a default. If there
is no pin-compatible alternate, either:

* pick a different part, or
* record the risk in the design docs and, where it is cheap, lay out a
  footprint that accepts an alternate.

## Consolidate aggressively

Fewer distinct part numbers beats locally optimal values. One resistor series
across the board, one capacitor family per voltage class. A BOM with 14
resistor values is cheaper to buy, place and stock than one with 40.

Before adding a value, check whether one already on the BOM will do.

## Design out the marginal part

If a part is marginal on temperature, voltage or tolerance at any corner, it is
the wrong part — do not "watch it in test". Derate deliberately and write the
derating into the rationale.

## When the human overrules you

Write it down here or in the relevant reference file, with the reason, in the
same session. Then follow it.
