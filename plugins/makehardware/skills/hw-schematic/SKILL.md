---
name: hw-schematic
description: House practice for a schematic a human can actually read - how to split a design into sheets from the agreed block diagram, where on the sheet each thing goes, and the gate that checks it. Use before starting schematic capture, whenever a sheet is being laid out or re-laid out, when a schematic needs to go in front of a reviewer, and when asked whether a drawing is readable or why a sheet is too big. Konnect's kicad-schematic skill does the placing and wiring; this decides what goes where and what good looks like.
---

# Drawing a schematic somebody can read

Konnect will place a symbol anywhere you tell it to. That is the problem.
Nothing in the toolchain has an opinion about *where*, so a capture loop that
is only trying to satisfy a netlist produces a drawing that is electrically
correct and visually unreadable — and the review that was supposed to catch
the design error instead gets spent on deciphering the picture.

The rule this skill exists to enforce:

> **A schematic is a document, not a netlist with coordinates.** Its job is to
> let a human find a circuit, follow it, and judge it. If it does not do that,
> it does not matter that it is correct.

Run the gate:

```bash
sch-lint hw/probe.kicad_sch                    # the report
sch-lint hw/probe.kicad_sch --gate             # exit 1 on any ERROR
sch-lint hw/probe.kicad_sch --svg docs/design/lint      # the findings, drawn
sch-lint hw/probe.kicad_sch --plan hw/block-diagram.yaml
```

`--svg` is the one to use in a review: it writes a light overlay of the sheet
with every finding circled and numbered. About three hundred elements against
the sixty thousand a real KiCad plot costs, so it inlines on the review page
and renders on github.com, which the plot does not.

## Before any symbol is placed: plan the sheets

Capture starts from `hw/block-diagram.yaml`, not from a blank page. The
architecture was already agreed with a human at the architecture review; the
sheet plan is that agreement turned into pages.

The default partition, which you deviate from only for a reason you write down:

| Sheet | Carries | Why it is its own sheet |
|---|---|---|
| 1 | **Root** — one hierarchical block per sheet below, wired to each other | It is the block diagram. A reviewer who has seen the block diagram can read page 1 in ten seconds. |
| 2 | **Power** — the whole tree: input, protection, every regulator, every rail's bulk | A rail is a system-level object. Split across sheets, nobody can see the tree. |
| 3 | **Processor core** — the MCU/SoC, its crystal, reset, boot straps, debug header, and *its* decoupling | Decoupling lives beside its part, never on a "capacitors" sheet. |
| 4..n | **One sheet per functional group** — one sensor chain, one radio, one motor driver | One sheet, one job. A sheet you cannot name in three words is two sheets. |
| last | **Connectors, test points, mounting, fiducials** | The mechanical/external interface, which is what someone bringing the board up looks at first. |

`sch-lint --plan hw/block-diagram.yaml` checks this bound the other way: every
block the human agreed to has to appear on exactly one sheet. A block in the
agreed architecture and on no sheet was dropped without a decision, and that is
the failure this catches — silently, otherwise, until layout.

See `references/sheet-plan.md` for how to derive the plan and how to size a
sheet before you fill it.

## The rules, and what each one costs when broken

Full list with the reasoning in `references/readability.md`. The short version,
in the order they bite:

**Signal flows left to right, power flows top to bottom.** Inputs and their
connectors on the left, processing in the middle, outputs and their connectors
on the right. Rails drawn upward out of a part, grounds downward. This is the
one convention every reader already has, and every violation costs them a
re-read of the sheet. `SCH-FLOW`, `SCH-PWRDIR`.

**Everything on the 1.27 mm grid.** Not aesthetics — a pin 0.01 mm off grid
looks connected and is not, and ERC will not tell you. `SCH-GRID`.

**Wires orthogonal.** No diagonals. `SCH-DIAG`.

**Every net that matters carries a name a human chose.** `3V3_ANA`, not
`Net-(U2-Pad3)`; `SPI1_MOSI`, not `N$32`. A net name is the only handle a
reviewer, a layout engineer and a bring-up engineer share. `SCH-AUTONET`.

**Use labels instead of long wires.** Past about a third of the sheet, a wire
is worse than a label: it crosses things, and following it is work. Short stub,
name it, move on.

**Decoupling is drawn beside the pin it decouples.** Not in a row at the edge
of the sheet. A cap drawn 60 mm from its IC is a cap that ends up 12 mm from it
on the board, because whoever placed the board read the schematic. `SCH-DECAP`,
and then `pcb-lint`'s `PCB-DECAP` measures the copper.

**One text size.** 1.27 mm, with 1.524 and 2.54 for headings. Five sizes on a
sheet reads as five levels of importance that do not exist. `SCH-TEXTSIZE`.

**Designators count the way the eye moves** — left to right, top to bottom, per
sheet. Someone is holding a BOM line looking for R47. `SCH-ANNOT`.

**A filled title block, and the same revision on every sheet.** A printed sheet
with no name, revision or date is not a document, and two sheets at different
revisions means nobody can say which drawing was agreed to. `SCH-TITLE`,
`SCH-REVSKEW`.

**Hierarchical pins match the child's labels exactly.** `VPP-MCLR` against
`VPP_MCLR` is a broken connection that looks fine on both pages.
`SCH-SHEETPIN`.

**A sheet the review page cannot embed is a sheet nobody will review.** KiCad
writes one path per glyph stroke, so an ordinary A4 sheet is 60,000 SVG
elements and three megabytes — twice what `hw-review`'s page can inline. Over
budget is not a rendering problem, it is too much on one page. `SCH-DENSITY`.

## Doing the work

1. **Sheet plan first**, from `hw/block-diagram.yaml`. Write it down in
   `docs/design/` before placing anything.
2. **Create the sheets and the hierarchy**, then the sheet pins, then wire the
   root. Page 1 should look like the block diagram.
3. **Fill one sheet at a time**, in reading order: connectors and inputs on the
   left edge, the main part in the middle, outputs right. Place the main part
   first, then its decoupling against its power pins, then everything else.
4. **Name every net as you make it.** Renaming later is a diff nobody reviews.
5. **Run `sch-lint` after every sheet**, not at the end. Every finding is
   cheaper now than after the next sheet.
6. **Run ERC as well** — `kicad-cli sch erc` — and put the count in the review
   summary as a number, not as an attachment.
7. **Export and look at it yourself** before showing anyone. Half of what a
   reviewer would catch, you will catch first.

All edits go through **Konnect**, always. Direct edits to a `.kicad_sch`
corrupt it. `sch-lint` only ever reads.

## Setting up a new project's schematic

```bash
# The house drawing sheet: A3 frame, title block wired to the project fields.
cp "${CLAUDE_PLUGIN_ROOT}/templates/kicad/makehardware.kicad_wks" hw/
```

Then point the project at it (`Page Settings -> Drawing sheet`, or
`schematic.page_layout_descr_file` in the `.kicad_pro`), and load the house
grid and text defaults through Konnect's `save_project_config` from
`templates/kicad/konnect-house.json`. `/hw-new-project` does both.

A3 is the default because A4 forces a split that is about paper rather than
about function, and a sheet split for the wrong reason is worse than a slightly
full one.

## What this skill is not

It is not a circuit-design skill. What the circuit *should be* comes from the
requirements, the block diagram, `hw-sourcing` for the parts and the datasheet
for the topology. This is only about the drawing — which is the half that
decides whether anybody catches the mistake in the other half.
