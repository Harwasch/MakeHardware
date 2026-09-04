---
name: hw-pcb-layout
description: House practice for laying out a board that works and can be reviewed - placement order, stackup and reference planes, decoupling geometry, return paths, silkscreen an assembler can read - plus pcb-lint, the pre-route gate that measures it. Use before placing footprints, while placing or re-placing them, before routing, before generating fabrication output, and when asked whether a board is ready or why a router will not route it. Konnect's kicad-pcb skill does the placing and routing; this decides where things go and what has to be true before a track is drawn.
---

# Laying out a board

A schematic that is right can still produce a board that does not work, and
the failures are geometric: a decoupling capacitor twelve millimetres from the
pin it serves is not a decoupling capacitor, a signal layer with no reference
plane beside it has no return path, and a via array under an exposed pad lands
on whatever is opposite.

None of those are DRC errors. DRC checks that the copper obeys the rules you
gave it; it has no opinion about whether the rules or the placement were any
good. That is what this skill and `pcb-lint` are for.

```bash
pcb-lint hw/probe.kicad_pcb                     # the report
pcb-lint hw/probe.kicad_pcb --gate              # exit 1 on any ERROR
pcb-lint hw/probe.kicad_pcb --svg docs/design/pcb-lint.svg
pcb-lint hw/probe.kicad_pcb --keepout J5=6.60   # check a constant against the part
```

The `--svg` is the board drawn at 1:1 with every finding numbered on it and
every decoupling loop drawn as a coloured line with its length written beside
it. That is the picture a layout review actually needs; a render shows a human
nothing they can act on.

**Net classes are not in the `.kicad_pcb`.** They are in the sibling
`.kicad_pro`, under `net_settings.classes`. This is worth knowing before you go
looking: a script that searches the board file for them finds nothing and
concludes the board is fine.

## Order of work, and why this order

1. **Stackup first, before a single footprint.** Layer count, which layers are
   planes, and what each signal layer references. Changing it later re-routes
   the board.
2. **Board outline, mounting holes, keepouts and connectors.** These are
   mechanical constraints from the enclosure, not layout choices — read the
   dimensions from `cad/`, never from memory.
3. **Check the net classes against the footprints, before placing.** Arithmetic,
   one minute, and it is what stands between you and a router that returns
   almost every connection as a failure. `pcb-lint --only PCB-TRACKW,PCB-CLEAR`.
4. **Place by function, in the same groups as the schematic sheets.** Power
   input to regulator to load, following the current. Sensitive analogue away
   from switching nodes. The board should be recognisably the block diagram.
5. **Place decoupling with its IC, not after.** Cap on the same side, against
   the pin, ground via at the cap's ground pad. This is placement, not routing.
6. **Run DRC on the placed, unrouted board.** Before a single track. It found
   721 errors on one board, three of them real, and every one of those three
   would otherwise have been found after routing, when fixing it means
   re-routing.
7. **Route the critical nets by hand** — switching node, feedback, crystal,
   differential pairs, anything with a current spike in it. Then the rest.
8. **Pour, re-run DRC, then `pcb-lint --gate`, then look at the render.**

## The rules `pcb-lint` measures

| Code | Rule | Section |
|---|---|---|
| `PCB-THERMVIA` | A `_ThermalVias` footprint's via array must not land on opposite-side copper on another net | §3 |
| `PCB-TRACKW` | A net class track width must fit the narrowest pad on its nets | §1 |
| `PCB-CLEAR` | A net class clearance must be smaller than the pad gaps inside its own footprints | §1 |
| `PCB-KEEPOUT` | A keepout radius must come from the footprint, not from memory | §4 |
| `PCB-DECAP` | Decoupling loop length, ranked worst first | — |
| `PCB-SILK` | No silkscreen crossing a pad | — |
| `PCB-REFTEXT` | A reference designator an assembler can read | — |
| `PCB-COURTYARD` | No overlapping courtyards, by real polygon area | §5 |
| `PCB-REFPLANE` | Every signal layer next to a reference plane | — |

Sections are in `hw-verification/references/pcb-layout.md`, which is where the
diagnosis stories live. Read it once; every one of those hours was spent
looking somewhere else first.

## The rules nothing measures, which you have to hold

**Return current follows the signal, not the schematic.** Above a few
kilohertz, return current runs directly under its trace in the nearest plane.
So a gap or a slot in the plane under a fast signal is a loop the size of the
detour, and it radiates. Never route a fast signal across a plane split.

**Every layer change is a return-path change.** A signal that vias from one
layer to another needs its return to via too — a ground stitching via next to
the signal via, within a couple of millimetres. Without it the return goes the
long way round.

**Decoupling is a loop, not a distance.** The loop is IC power pin → cap →
cap's ground pad → ground via → plane → back to the IC's ground. Shortening
the power side and leaving 8 mm of ground return achieves nothing.
`pcb-lint` reports both halves separately for that reason.

**Place the small capacitor closest.** A 100 nF at 1 mm and a 10 µF at 5 mm,
not the other way round. The small one is the high-frequency one, and it is
the one that cares about the millimetre.

**Analogue and switching share a board, not a return path.** Keep the
switching-converter loop — input cap, switch, inductor, output cap — physically
tiny and on one side, and keep the analogue ground referenced away from it.

**Silkscreen is for the human who assembles and debugs the board.** Reference
designators outside the courtyard, readable from one direction, pin 1 marked on
every polarised part, connectors labelled with what they connect to. A board
with hidden refdes is a board nobody can find a part on.

**Test points are a design feature.** Every rail, every reset, every bus, and
the ground next to them. Add them at placement, not after bring-up fails.

## Then look at it

```bash
kicad-cli pcb drc hw/probe.kicad_pcb --output docs/design/drc-report.rpt \
    --severity-error --severity-warning
kicad-cli pcb render hw/probe.kicad_pcb --output docs/design/pcb-top.png \
    --side top --quality high --width 1600 --height 1200
kicad-cli pcb render hw/probe.kicad_pcb --output docs/design/pcb-bottom.png \
    --side bottom --quality high --width 1600 --height 1200
```

Both sides, always — the opposite side of a board is where the surprises are.
Put the DRC count in the review as a number, and the stackup as a table. See
`hw-review/references/exports.md`.

All board edits go through **Konnect**, or through KiCad's own `pcbnew` Python
API when the IPC socket is not responding. Never text-edit a `.kicad_pcb`.
`pcb-lint` only ever reads.
