# Every rule, and the failure it prevents

Each rule below has a `sch-lint` code beside it. A rule with no code is one
nothing can check yet — treat those as the ones needing the most attention,
because nothing else will catch them.

---

## 1. Direction

### Signal flows left to right — `SCH-FLOW`

Inputs and their connectors on the left edge, processing in the middle,
outputs and their connectors on the right. Feedback is the exception and is
drawn returning above or below the forward path, never through it.

This is not taste. A reader arrives at a sheet with an expectation about where
things are, and every sheet that violates it costs a full re-read. On a design
review that is the difference between a reviewer spending their attention on
your circuit and spending it on your drawing.

`sch-lint` reports the flow as a number — the mean normalised x of the outputs
minus that of the inputs — and warns below +0.15. It never gates: a power
sheet legitimately flows top to bottom and a connector sheet flows nowhere.

### Power flows up, ground flows down — `SCH-PWRDIR`

A rail symbol points up out of the part it feeds; a ground symbol points down.
A reader scans a sheet for supply structure by silhouette, before reading a
single label. A ground drawn sideways breaks that read for the whole sheet, and
`sch-lint` finds them by comparing each power symbol's body centroid against
its pin.

Corollary: on a part with power pins on the left and right, do not route the
rail through the body. Bring it in at the top.

---

## 2. Geometry

### The 1.27 mm grid — `SCH-GRID`

Everything electrical: symbol origins, pin ends, wire endpoints, junctions,
labels, sheet pins. 1.27 mm is 50 mil, KiCad's default, and the pitch every
library is drawn on.

The failure is not ugliness. **A pin 0.01 mm off the grid looks connected and
is not**, ERC reports nothing, and the defect surfaces as a net missing from
the netlist at layout time. It is the cheapest possible check and it catches
one of the most expensive possible mistakes.

Property *text* positions are deliberately not checked. KiCad's autoplacer
writes a reference at (27.3812, 91.5416) on a design that is otherwise
perfectly on-grid; checking those emits about forty errors on finished work,
and a gate that fires on clean work is a gate somebody switches off.

### Wires orthogonal — `SCH-DIAG`

No diagonals, ever. A diagonal wire cannot be followed across a crossing,
cannot be aligned with anything, and reads as an error even when it is not.
Graphic polylines — a dashed box around a functional group — are exempt and
are encouraged.

### Nothing overlapping — `SCH-OVERLAP`

Two symbol bodies overlapping by more than 0.5 mm² is a drawing defect. It
usually means an automated placement pass ran without a courtyard concept.
Stacked power flags are excluded, because stacking them is deliberate.

---

## 3. Naming

### One net, one name, chosen by a human — `SCH-AUTONET`

`3V3_ANA`, not `Net-(U2-Pad3)`. `SPI1_MOSI`, not `N$32`. `THERM_SENSE`, not
`Net-(R14-Pad2)`.

The net name is the only handle shared by the schematic reviewer, whoever lays
out the board, whoever writes the test plan and whoever brings the board up at
2 a.m. An auto-generated name carries the one fact nobody needs — which pad the
autonamer happened to reach first — and destroys the one they do.

Conventions worth holding to:

* Rails by voltage and domain: `3V3`, `3V3_ANA`, `5V_USB`, `VBAT`.
* Grounds by domain: `GND`, `AGND`, `PGND`. If there is only one, `GND`.
* Buses by peripheral and signal: `I2C1_SDA`, `SPI2_SCK`, `UART_DEBUG_TX`.
* Nets that cross a sheet get a name whether or not they need one. Nets local
  to a corner of one sheet do not.

`sch-lint` warns on an unnamed or auto-named net carrying four or more pins.
Three-pin local nets are ordinary and are left alone.

### Designators in reading order — `SCH-ANNOT`

Per sheet, per prefix: left to right, top to bottom. Someone is holding a BOM
line looking for R47 on a printed sheet; scattered annotation turns that into a
search. Re-annotate rather than arguing about it — it is one command and it is
never controversial.

### Value fields say the value — nothing checks this

`100nF 16V X7R 0603`, not `C`. `10k 1% 0402`, not `RES`. The value on the sheet
is what a reviewer checks against the datasheet; making them open the BOM to
find out what the part is defeats the point of drawing it.

---

## 4. Layout of a sheet

### One sheet, one job

If you cannot name what a sheet does in three words, it is two sheets. Group
related circuits and put a dashed graphic box around each group with a text
label — a "Boost converter, 3V3 -> 13V" box costs four polylines and saves
every reader thirty seconds.

### Labels beat long wires — nothing checks this

Past about a third of the sheet's width, a wire is worse than a label: it
crosses other wires, and following it is work. Draw a short stub, name it, and
put the matching stub where it is used. Buses for anything that travels
together — an address bus, a segment drive, an eight-channel ADC front end.

The failure mode in the other direction is real too: a sheet where *everything*
is a label is a sheet with no visible topology. Wire what is local; label what
travels.

### Decoupling beside the pin — `SCH-DECAP`

Every bypass capacitor is drawn immediately beside the power pin it serves,
with its ground symbol directly below it. Never a row of capacitors at the edge
of the sheet, and never on a separate "passives" sheet.

This is a *drawing* rule with a *layout* consequence, which is why it is worth
a gate. Whoever places the board reads the schematic; a cap drawn 60 mm from
its IC is placed 12 mm from it, and 12 mm of trace at 100 MHz is not a
decoupling capacitor. `pcb-lint`'s `PCB-DECAP` then measures the copper.

`sch-lint` warns past 25.4 mm and errors past 50.8 mm, and always errors when
the cap is on a different sheet from its IC.

### Pin ordering follows function, not the package — nothing checks this

Draw an IC symbol grouped by function: power at the top, grounds at the bottom,
inputs left, outputs right, control and configuration wherever it keeps the
wires short. A symbol laid out in physical pin order is a symbol that forces
every reader to do the mapping the symbol was supposed to do for them. Split a
large part into functional units rather than drawing an 80-pin rectangle.

---

## 5. Typography and the frame

### One text size — `SCH-TEXTSIZE`

1.27 mm, with 1.524 mm and 2.54 mm available for headings. Five sizes on a
sheet reads as five levels of importance, and there are not five.

### A filled title block, and one revision across the set — `SCH-TITLE`, `SCH-REVSKEW`

Title and revision are errors when missing; date and company are warnings. A
set of sheets at mixed revisions is a warning that matters more than it looks:
it means nobody can say which drawing the human agreed to at the review, which
is the whole basis of `review-gate`.

### A drawing sheet that is the house one

`templates/kicad/makehardware.kicad_wks`. A3, a title block wired to the
project's own fields, and a note saying the drawing is generated. Consistency
across projects is worth more than any individual frame.

---

## 6. Hierarchy

### Page 1 is the block diagram — `SCH-PLAN`

The root sheet carries one hierarchical block per sheet below it, wired to each
other, and nothing else. A reviewer who has already agreed to
`hw/block-diagram.yaml` should recognise page 1 immediately. Keep the tree one
level deep unless a sub-assembly genuinely repeats.

`sch-lint --plan hw/block-diagram.yaml` checks the binding: every block in the
agreed architecture appears on exactly one sheet. A block that reaches no sheet
was dropped without a decision — the exact failure the architecture review
exists to prevent, arriving two stages later where it costs a respin.

### Sheet pins match the child's labels exactly — `SCH-SHEETPIN`

`VPP-MCLR` on the parent against `VPP_MCLR` in the child is a broken connection
that looks correct on both pages. `sch-lint` reports the near-miss by name so
the fix is obvious.

Directions have to agree too: a pin declared `input` on the parent against a
label shaped `output` in the child is a warning worth reading.

### A sheet the review page cannot embed — `SCH-DENSITY`

KiCad's SVG exporter writes one path per line segment, glyph strokes included.
An ordinary A4 sheet measures around 60,000 elements and three megabytes,
against the 30,000/1.5 MB budget `hw-review/references/exports.md` documents
for a single inlined SVG.

Do not try to solve this by exporting smaller. It is not a rendering problem —
it is a sheet with too much on it. Split it.

`sch-lint` shells out to `kicad-cli` and measures, because the number cannot be
estimated: the two committed example sheets measure 60 and 29 elements per
rendered character, a factor of two apart on the same design. Where `kicad-cli`
is unavailable the estimate only warns, and only when it is half again over.

---

## What nothing checks, and you have to

* **Is the circuit right.** Everything above is about the drawing.
* **Does the symbol match the datasheet pinout.** A symbol with two pins
  swapped passes every check here and every ERC.
* **Are the values right.** `100nF` where the datasheet says `1uF` is invisible
  to a linter.
* **Is anything missing.** A pull-up that was never drawn has no defect for a
  gate to find. This is what the block diagram and the requirements trace are
  for, and it is why `SCH-PLAN` is the check worth caring about most.
