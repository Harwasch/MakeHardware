---
name: hw-block-diagram
description: Settle the electrical architecture as a functional block diagram before schematic capture - the major ICs, the power tree with a current budget, and the data buses - written as a spec that renders to an editable draw.io file and a review image. Use after requirements and before any schematic work, when asked for a block diagram or an architecture, when the power tree or a rail budget is in question, or when a new IC or bus is added to a design.
---

# Electrical block diagram

The block diagram is the architecture agreement. It comes **after requirements
and before schematic capture**, and it answers three questions that are
expensive to answer later:

* **What major parts exist?** The ICs, connectors and modules — not passives.
* **What powers each of them?** The whole power tree, with a current budget.
* **What talks to what?** The data buses, with their controllers.

Finding out during layout that the 3.3 V rail is 400 mA short is a respin.
Finding out here is an edit.

## The spec is the source of truth

`hw/block-diagram.yaml` is written by hand. Both outputs are generated from it,
so the editable file and the review image cannot drift apart:

| File | What it is |
|---|---|
| `hw/block-diagram.yaml` | the spec — **the only file you edit** |
| `hw/block-diagram.drawio` | editable diagram, opens in draw.io and the VS Code extension |
| `docs/design/block-diagram.svg` | the review image, renders inline on GitHub |
| `docs/design/block-diagram.png` | optional raster, for slides — `--png` |

```bash
block-diagram              # write all three, then print the power budget
block-diagram --check      # validate only; exit 1 on a broken tree or an over-budget rail
block-diagram --summary    # power budget per rail, no files written
block-diagram --png        # also rasterise
block-diagram --relayout   # discard hand-tidied positions and lay out fresh
```

Never hand-edit the `.drawio` or the `.svg` to change *content* — the next run
overwrites it. Moving blocks around in draw.io **is** fine and is the point:
positions are read back on the next run and reused, keyed by block id.

## What goes in, and what does not

**In:** ICs, regulators, connectors, modules, sensors, actuators, and anything
with a part number that a reviewer would ask about.

**Out:** decoupling caps, pull-ups, series resistors, test points. If it does
not appear in the power budget or on a bus, it belongs in the schematic, not
here. A block diagram with 60 blocks is a schematic drawn badly.

Aim for 6–25 blocks. If you have three, you have drawn a photograph of the
datasheet's typical application circuit.

## The power tree is the part that earns its keep

Every rail declares what makes it and what it can deliver; every block declares
what it draws. The tool then does the arithmetic you would otherwise do wrong:

```yaml
rails:
  - id: V3P3
    voltage: 3.3
    from: VBUS          # the rail that feeds it
    source: U2          # the block that converts it
    max_current_a: 2.0  # what the source can actually deliver

blocks:
  - id: U1
    name: MCU
    kind: mcu
    part: STM32H563ZIT6
    powered_by:
      - rail: V3P3
        typ_current_a: 0.11
        max_current_a: 0.28
```

A rail carries its own loads **plus everything drawn by the rails derived from
it**, referred through their regulators. Converter efficiency is deliberately
not modelled — this is a headroom check, not an energy model, and inventing a
curve at an unknown operating point would be worse than a conservative number.
If you need the input-side number for a thermal or battery-life claim, work it
out explicitly and record it in an ADR.

`--check` exits 1 when a rail's max draw exceeds what its source can deliver,
and names the contributors largest first. Wire it into the same place you run
`req-trace --gate`.

### Currents come from datasheets

`max_current_a` is a number someone has to defend. Take it from the datasheet
at the operating condition you actually intend — not the typical at 25 °C when
you will run it at 85 °C, and not from memory. If the datasheet cannot be
fetched, record the block as blocked in `docs/reference/manifest.yaml` and ask
the human, exactly as `hw-documentation` requires. A budget built from guesses
that passes is worse than no budget, because it will be believed.

Declare peak, not average, unless there is a bulk capacitor sized to cover the
difference — and if there is, say so in the rail's `notes`.

## Buses

A bus with a `controller` and `members` draws as a shared spine; a two-block
link uses `between`. Put the thing that matters for layout in `notes` — the
clock rate, the number of chip selects, whether it is a differential pair.

```yaml
buses:
  - id: SPI1
    kind: spi
    controller: U1
    members: [U5, U6]
    notes: 10 MHz, two chip selects
  - id: USB2
    kind: usb
    between: [J1, U1]
    notes: full speed
```

`kind` is one of `usb i2c spi uart can ethernet i2s swd gpio analog rf`, which
sets the colour. Anything else still draws, in grey.

Two buses that are alternates for the same connection (an IMU wired for either
SPI or I2C) should both appear, with the choice recorded in `notes`. That is
real design information and it disappears the moment someone picks one.

## Reading the warnings

The tool distinguishes what is broken from what is suspicious, and only the
first kind is an error:

* *"nothing powers it"* — usually a missing `powered_by`, occasionally a block
  that genuinely runs off a bus, like a USB device.
* *"on no bus"* — either a missing bus or a block that should not be here.
* *"is higher than its parent"* — a step-up that is not declared as one. Almost
  always a typo in a voltage.
* *"no current declared"* — the block is invisible to the budget. Fix it or the
  budget is a lie by omission.

Do not silence a warning by deleting the block. Say what you found.

## Exit condition

The block diagram is done when the human has looked at the image and agreed to
it, and:

* every block has a part number, or an explicit "TBD" with the decision named
  as a chunk in `plan.yaml`;
* every rail has a declared limit, and `--check` passes;
* every current in the budget traces to a datasheet in `docs/reference/`;
* each requirement that constrains the architecture — a power budget, an
  interface, a part choice — has a `File` relation to
  `hw/block-diagram.yaml`, so `req-trace` can see it.

Then, and only then, start schematic capture. Konnect builds the schematic; the
block diagram is what tells it what to build.

## When the design changes

It will. When a part changes or a rail moves, edit the spec and re-render **in
the same session** — a block diagram that disagrees with the schematic is worse
than none, because it is the document reviewers read first. If the change
invalidates a decision recorded in an ADR, update the ADR too; `hw-documentation`
covers how.
