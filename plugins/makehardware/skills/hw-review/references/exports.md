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

`vision-board` already does this and it is not only for the vision stage —
point it at any concept-shaped module:

```bash
vision-board cad/enclosure.py --out docs/design/enclosure \
    --doc docs/design/enclosure.md --project "Enclosure, rev C"
```

For an assembly, export STEP for anyone who wants it in CAD — and **STL as
well**, because GitHub renders STL in an interactive 3D viewer in the blob
view. That is the one case where the human can rotate and zoom the actual
geometry without installing anything, and it beats any static render:

```bash
/opt/hw-py/bin/python -c "
from build123d import export_step, export_stl
import cad.enclosure as m
export_step(m.PART, 'docs/design/enclosure.step')   # for CAD
export_stl(m.PART, 'docs/design/enclosure.stl')     # for GitHub's 3D viewer"
```

Keep the STL coarse enough to stay small — it is for looking at, not for
manufacturing — and say in the review request that it is a review mesh.

A cross-section render is still usually the most informative single *image* of
an enclosure: it shows the wall thicknesses, the internal clearances and where
the board actually sits, and it is the one view a 3D viewer will not give you
by default.

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

The SVG renders on GitHub; the `.drawio` is the editable one. Put the power
budget table in the review summary — a rail at 95% of its limit is the single
most useful thing in an architecture review and it is invisible in the
picture.

## Simulation

Numbers, in a markdown table, in `docs/design/`. A `.raw` file is not a
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

Before anything is ordered, the human reviews: the gerber render (not the
gerbers), the drill count and sizes, the stackup, the assembly drawing, and
the BOM with stock and lead times as of the date you checked. Ordering parts
is expensive and irreversible; it is exactly the point where an extra
question is cheap.

---

## Writing the summary that goes with it

The artefact is what they look at. The summary is what makes them look at the
right part of it. Three or four sentences:

1. What this is, and what changed since they last saw it.
2. The number or the choice you want confirmed.
3. What you are least sure about.
4. What happens next if they say yes.
