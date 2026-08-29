# Making a design reviewable from a browser

Every recipe here turns something only an application can open into something
github.com renders. Run it, look at the result yourself, commit it, then open
the review.

Keep the exports under `docs/design/` (or `docs/review/`) rather than `build/`
— `build/` is gitignored, and an artefact that is not committed is an artefact
nobody sees.

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

**Prefer the per-sheet SVGs over the PDF for anything under about four
sheets.** Pass the SVG directory as an `--artifact` and `review-gate` embeds
each sheet inline in the review packet, so the human scrolls one page instead
of opening GitHub's PDF viewer — which is serviceable on a desktop and
unpleasant on a phone. Commit the PDF too, for printing and for anyone who
wants the whole thing in one file.

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
