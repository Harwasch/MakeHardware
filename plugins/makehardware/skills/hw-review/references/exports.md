# Making a design reviewable from a browser

Every recipe here turns something only an application can open into something
github.com renders. Run it, look at the result yourself, commit it, then open
the review.

Keep the exports under `docs/design/` (or `docs/review/`) rather than `build/`
— `build/` is gitignored, and an artefact that is not committed is an artefact
nobody sees.

## Export at review size, not at native size

Two different consumers, two different limits, and the second one bites:

* **GitHub** will render whatever you commit, at any size.
* **The review page** (`review-artifact`) has three budgets, and the whole
  page has to stay inside the 16 MB artifact cap:

  | | Limit | What blows it |
  |---|---|---|
  | raster, as a data URI | 220 kB | `pcb render --width 3000`, `dpi=300` |
  | one SVG | 1.5 MB / 30,000 elements | any dense plotted schematic |
  | one `.glb` model | 2.5 MB | exporting at manufacturing tolerance |
  | the page, in total | 9 MB inlined | a tab with six sheets on it |

  Anything over is reported on the page instead of shown, which is honest but
  is not a review.

**A plotted schematic is far bigger than you expect.** KiCad's SVG exporter
writes one `<path>` per *line segment*, including every stroke of every
character of text. Measured on KiCad's own `pic_programmer` demo:

```
root sheet   3.0 MB    61,681 elements     linked, not inlined
sub-sheet    1.0 MB    21,265 elements     inlines fine
```

So one ordinary A4 sheet can be a megabyte, and a four-sheet design will not
fit. Put the two or three sheets that carry the decision on the page, commit
the PDF for the whole set, and say in the request which sheets you chose.

So export twice when it matters: full size for the record, and a review-sized
copy for the page.

```bash
kicad-cli pcb render hw/probe.kicad_pcb --output docs/design/pcb-top.png \
    --side top --quality high --width 1400 --height 1000     # ~150-200 kB
```

For matplotlib, `savefig(..., dpi=110)` on a 7×5 in figure lands around 150 kB.

**A plotter's colours cannot be themed, and that is fine.** KiCad fills the
page with `#F5F4EF` and draws in black, written inline on every `<g>`, so no
stylesheet on the page can reach it. The review page detects a full-page light
fill and mats the sheet, the way it mats an opaque raster — a schematic then
reads as a sheet of paper on a dark page rather than a hole in it. Do not try
to recolour a plot for the page: it would misrepresent what you exported.

**Export rasters with a transparent background** where the tool allows it —
`savefig(..., transparent=True)`, which `vision-board` already does. A render
exported against white is a bright slab on a dark page; the review page mats
those deliberately so they read as a mounted photograph, but transparent is
better. And **never bake a title or a label into a raster**: a bitmap cannot
follow the reader's theme, so dark text in it stays dark on a dark page. Labels
belong in the caption or in an SVG overlay.

**Prefer SVG wherever the thing is line art** — a schematic, a plot, a diagram,
a dimensioned drawing. It inlines as markup, stays crisp at any zoom, themes
with the page, and has no byte budget at all. Reserve rasters for what is
genuinely photographic: a shaded 3D render, a photo of a board.

Run `review-artifact --check` before publishing. It exits 1 and names every
artefact that could not be embedded, which is much cheaper than finding out
from the human.

---

## The lint overlays — the cheapest useful picture there is

```bash
sch-lint hw/probe.kicad_sch --svg docs/design/lint
pcb-lint hw/probe.kicad_pcb --svg docs/design/lint/board.lint.svg
```

Each writes the artefact drawn at 1:1 with every finding circled, numbered and
listed underneath. About three hundred elements against the sixty thousand
KiCad's own plot of the same sheet costs, so they inline on the page *and*
render on github.com — which the real plot does not.

Put these on the review page next to the plot, not instead of it. The plot is
what the design is; the overlay is what is wrong with it.

## KiCad schematic

```bash
kicad-cli sch export pdf hw/probe.kicad_sch \
    --output docs/design/schematic.pdf

# One SVG per sheet, which renders inline in markdown rather than needing
# GitHub's PDF viewer. Worth it for a design with one or two sheets.
kicad-cli sch export svg hw/probe.kicad_sch \
    --output docs/design/schematic/

# The netlist and the ERC report belong with them: they are what makes the
# review a review rather than a look.
kicad-cli sch erc hw/probe.kicad_sch \
    --output docs/design/erc-report.rpt --severity-error --severity-warning
kicad-cli sch export bom hw/probe.kicad_sch --output docs/design/bom.csv
```

`--black-and-white` if the colour plot is hard to read. Put the ERC result in
the review summary as a number — "ERC: 0 errors, 3 warnings, all
unconnected-pin on the debug header" — not as an attachment nobody opens.

**Prefer the per-sheet SVGs over the PDF, for the two or three sheets that
carry the decision.** Pass them as `--artifact` and `review-gate` embeds each
inline in the review packet, so the human scrolls one page instead of opening
GitHub's PDF viewer — serviceable on a desktop, unpleasant on a phone. Commit
the PDF too, for printing and for the sheets that did not make the page.

`sch export` offers PDF, SVG, DXF and PS — there is no PNG, in KiCad 10 either
— so a sheet too dense for the page has no smaller raster to fall back on.
Choose fewer sheets rather than hoping.

## KiCad board

```bash
# The board in 3D, which GitHub renders interactively in the blob view.
kicad-cli pcb export step hw/probe.kicad_pcb --output docs/design/pcb.step
# (and an STL alongside it if you want the viewer: kicad-cli has no STL
#  exporter, so convert the STEP, or export from build123d.)

# Layer plots, one page each, in one PDF.
kicad-cli pcb export pdf hw/probe.kicad_pcb \
    --output docs/design/pcb-layers.pdf \
    --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts \
    --include-border-title

# What it will look like. Both sides — the opposite side of a board is where
# the surprises are.
kicad-cli pcb render hw/probe.kicad_pcb --output docs/design/pcb-top.png \
    --side top --quality high --width 1600 --height 1200
kicad-cli pcb render hw/probe.kicad_pcb --output docs/design/pcb-bottom.png \
    --side bottom --quality high --width 1600 --height 1200

kicad-cli pcb drc hw/probe.kicad_pcb --output docs/design/drc-report.rpt \
    --severity-error --severity-warning
```

A layout review needs the stackup, the board outline with its overall
dimensions, and the DRC count as a number. A render alone shows a human
nothing they can act on.

## Mechanical (build123d)

One command, and it produces everything a mechanical review needs:

```bash
cad-export cad/enclosure.py --out docs/design/cad --name enclosure
```

| File | Where it is reviewed |
|---|---|
| `enclosure-render.png`, `-exploded.png`, `-section.png` | Inline, on the page and on GitHub |
| `enclosure-iso.svg` | Inline, line art, themes with the page |
| `enclosure.glb` | **The review page's orbit viewer** — drag to turn it over |
| `enclosure.stl` | **GitHub's own 3D viewer**, the only 3D format it renders |
| `enclosure.step` | Anyone who wants it in CAD: tree, names, colours, MATE_* datums |
| `enclosure-joints.json`, `-freecad.py` | The constraints STEP cannot carry |

Put the `.glb` in the phase's `images:` and the page builds the viewer. Commit
the `.stl` too and keep it coarse — it is a review mesh, not a manufacturing
one, and say so in the request.

**A cross-section is still the most informative single image of an enclosure.**
It shows the wall thicknesses, the internal clearances and where the board
actually sits, and it is the one view an orbit viewer will not give you by
default. `cad-export` writes one every time.

For a vision-stage concept rather than a finished assembly, `vision-board` is
still the tool — it renders one shape in one material, which is what a concept
is.

## Requirements

```bash
req-trace --map                     # docs/design/requirements-map.{svg,drawio}
/opt/hw-py/bin/strictdoc export requirements \
    --output-dir docs/design/requirements-html --formats=html
```

The SVG map is the artefact — it renders inline and shows the shape of the
tree, which is what a human can actually judge. The HTML export is complete
but GitHub will not render it; link it as a `--reference` and say it needs
downloading. **Do not generate the HTML export on every validation run and
never mention it**, which is what used to happen.

## Architecture

```bash
block-diagram                       # writes the .drawio and the .svg
block-diagram --summary             # the power budget, as text
```

The SVG renders on GitHub; the `.drawio` is the editable one. **Always emit
both.** The review page finds the `.drawio` that goes with a rendered diagram —
including across directories, which this pair needs, since the `.drawio` lands
in `hw/` and the SVG in `docs/design/` — and puts *Open in draw.io* under the
picture. That link hands diagrams.net the raw URL, so the human is one click
from an editable diagram with nothing to install and nothing to download. It
fetches anonymously, so it works on a public repository; on a private one they
download the file from GitHub and drop it on the canvas instead, and the link
to the file is there for exactly that.

The rule generalises: **a diagram you generate should have a `.drawio` beside
it.** A picture someone cannot change is a picture they can only complain
about.

Put the power budget in the review as a **chart**, not as a sentence:

```bash
hw-chart budget hw/rails.csv --out docs/design/power-budget.svg
```

A rail at 95% of its limit is the single most useful thing in an architecture
review, it is invisible in the block diagram, and it is the first thing the eye
lands on in a bar inside its own budget outline.

## Simulation

```bash
hw-chart corners docs/design/corners.csv --out docs/design/standby-corners.svg
hw-chart bode    docs/design/ac.csv      --out docs/design/loop-gain.svg
```

`hw-chart corners` draws the corners as small multiples on one shared scale,
with the spec line and the failing corner marked. `hw-chart bode` computes the
crossover, phase margin and gain margin **from the data** and annotates them —
a margin typed into a caption is a margin that stopped being true at the next
simulation.

Keep the numbers in a markdown table beside the chart. A `.raw` file is not a
result and a plot without the number beside it is decoration.

```markdown
| Corner | Measured | Required | Margin |
|---|---|---|---|
| 25 °C, 3.3 V nom | 38.2 µA | ≤ 40 µA | +4.5% |
| 85 °C, 3.0 V min | 41.7 µA | ≤ 40 µA | **−4.3% FAIL** |
```

Lead with the corner that fails. Commit the deck beside it so the run is
reproducible, and state which simulator produced the number.

## Fabrication output

Ordering parts is expensive and irreversible, so this is exactly the point
where an extra question is cheap. But the review here is **not** a gallery: a
fabrication drawing shrunk to page width tells nobody anything they can act
on, and nobody reads an assembly traveller inside a review page.

What the human needs at this stage is a **checklist** — the set of documents a
run requires, which of them exist, and one click to each. Give the phase a
`links:` list in `docs/review/artifact.yaml`, grouped with `group:`, and the
page renders it with a present/missing tally at the top:

```yaml
  - id: mfg
    links_title: Release checklist
    links:
      - {group: Fabrication, path: docs/design/pcb-fab.zip,
         label: Gerbers and drill files,
         why: "RS-274X plus the drill schedule"}
      - {group: Assembly, path: docs/design/mfg/assembly-process.md,
         label: Assembly and test process,
         why: "The traveller — paste, placement, reflow, then the test sequence"}
```

**List the documents that do not exist yet too.** A row saying *Not produced*
is the entire value of a checklist; a list of only what you have is a list
that cannot tell anyone what is missing.

Cover, at least: gerbers and drill, the fabrication drawing, the stackup, the
written fab notes, the assembly drawing, the pick-and-place, the BOM, the
assembly and test process, the test fixture, the quotes with their dates, and
which supplier was chosen and why.

---

## Writing the summary that goes with it

The artefact is what they look at. The summary is what makes them look at the
right part of it. Three or four sentences:

1. What this is, and what changed since they last saw it.
2. The number or the choice you want confirmed.
3. What you are least sure about.
4. What happens next if they say yes.
