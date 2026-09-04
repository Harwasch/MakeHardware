# Planning the sheets before drawing on any of them

Capture starts from `hw/block-diagram.yaml`. That file was agreed with a human
at the architecture review; the sheet plan is that agreement turned into pages,
and `sch-lint --plan` checks the two never drift apart.

## Derive it

```bash
block-diagram --summary        # the blocks, the rails, the current budget
```

Then write `docs/design/sheet-plan.md` — a table, committed, before any symbol
is placed:

```markdown
| Sheet | Name | Blocks from the architecture | Rails present |
|---|---|---|---|
| 1 | Root | (hierarchy only) | — |
| 2 | Power | VIN protection, U1 buck 5V, U2 LDO 3V3, VBAT charger | all |
| 3 | MCU | U3 STM32G031, crystal, SWD, boot straps | 3V3 |
| 4 | Sense | U4 instrumentation amp, thermistor front end, filter | 3V3, 3V3_ANA |
| 5 | Display | U5 segment driver, contrast, backlight | 3V3, 5V |
| 6 | Interface | J1 USB-C, J2 probe, TP1-8, mounting, fiducials | 5V_USB |
```

Two sentences under it: what you split and why, and anything you deviated from
the default partition for. That is what a reviewer reads when a sheet turns out
to be in the wrong place.

## The default partition

| Sheet | Carries |
|---|---|
| 1 | **Root.** One hierarchical block per sheet below, wired to each other. Nothing else. |
| 2 | **Power.** The whole tree in one picture: input, protection, every regulator, every rail's bulk, and the battery path if there is one. |
| 3 | **Processor core.** The MCU/SoC, crystal, reset, boot straps, debug header, and its own decoupling. |
| 4..n | **One sheet per functional group.** One sensor chain, one radio, one motor driver, one display. |
| last | **Interface.** Connectors, test points, mounting holes, fiducials. |

Deviate when a real reason says so, and write the reason down. Two that come up:

* **A repeated channel** — four identical sensor front ends — is one sheet
  instantiated four times, not four sheets. That is what hierarchy is for.
* **A very small design** — under about forty parts — can be one sheet, and
  splitting it into six makes it worse. Skip the hierarchy and say so.

## Two things that are always their own sheet

**The power tree.** A rail is a system-level object; split across sheets,
nobody can see the tree, and "is a rail missing" — the question the
architecture review exists to answer — becomes unanswerable from the drawing.

**Never a "passives" or "capacitors" sheet.** Every bypass capacitor belongs
beside the pin it decouples, on that pin's sheet. A capacitors sheet is the
single most common way a schematic becomes unreadable, and it propagates
straight into a board with 12 mm decoupling loops.

## Sizing a sheet before you fill it

The constraint that actually binds is not paper, it is the review page.
`hw-review/references/exports.md` gives a single inlined SVG 1.5 MB and 30,000
elements. KiCad writes one path per glyph stroke, so an ordinary A4 sheet
measures around 60,000 elements — twice the budget.

Rules of thumb that keep a sheet inside it:

* **Under about 35 placed symbols per sheet**, power symbols excluded.
* **One IC with more than about 30 pins per sheet**, plus its immediate
  support. A 100-pin MCU is its own sheet and probably two.
* **Page fill between 15% and 80%.** Below that, the sheet is too big for what
  is on it; above it, there is no margin left to read or to add anything.

Check it rather than trusting the rule:

```bash
kicad-cli sch export svg hw/probe.kicad_sch --output build/sheets/
sch-lint hw/probe.kicad_sch --svg-measure build/sheets/
```

`sch-lint` does this for you when `kicad-cli` is on `PATH`. When it is not, the
number in the header is a rough estimate and says so.

## Naming sheets

The sheet name shows on the root page, in the hierarchy navigator and on every
sheet's title block. Name it after **what the circuit does**, not after the
part: `Sense front end`, not `INA333`. Parts get substituted; jobs do not.

Filenames follow: `power.kicad_sch`, `mcu.kicad_sch`, `sense.kicad_sch`. The
root takes the project name.

## Wiring the root

Page 1 should be recognisably the same picture as
`docs/design/block-diagram.svg`, laid out the same way: sources left, sinks
right, power along the top. A reviewer who agreed to the block diagram then
reads page 1 in ten seconds and can go straight to the sheet they care about.

Bring out on a sheet pin only what genuinely crosses the boundary. A sheet with
forty pins is a sheet split in the wrong place — the partition, not the wiring,
is what needs fixing.

## Keeping it honest afterwards

```bash
sch-lint hw/probe.kicad_sch --plan hw/block-diagram.yaml --gate
```

Every block in the agreed architecture on exactly one sheet. Two failure modes,
both silent otherwise:

* **A block on no sheet** — dropped without a decision. This surfaces at
  layout, or at bring-up, or in the field.
* **A block on two sheets** — usually a part duplicated during a copy-paste of
  a similar circuit, and it produces two BOM lines and one part.

When the architecture legitimately changes, change `hw/block-diagram.yaml`
first, re-run `block-diagram --check`, and re-open the architecture review —
`review-gate` will already be reading stale, because the artefact the human
signed has moved.
