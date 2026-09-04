---
name: hw-verification
description: Close out hardware requirements against evidence and report honest coverage, and run the pre-route and pre-fabrication checks that catch a defect before it is expensive. Use at the end of a design sprint, before claiming a design is done, before placing or routing a PCB, before generating fabrication output, or whenever asked "does this meet the requirements" or "what is left".
---

# Verification

Verification is the step where claims become evidence. It is also the step
where it is easiest to be quietly dishonest, so the rules are narrow.

## The only way a requirement becomes Verified

All four, or it stays where it is:

1. `VERIFICATION` names how it was closed — Analysis, Simulation, Test or
   Inspection.
2. `EVIDENCE` points at something a person can go and look at: a committed
   simulation deck and its result, an ERC/DRC report, a measurement log, a
   calculation.
3. A `File` relation links the requirement to the design artefact that
   realises it.
4. The evidence actually shows the number in the `STATEMENT` being met, at the
   corners that matter — not just at nominal.

Never set `STATUS: Verified` to make the gate pass. If a requirement cannot be
met, say so and propose the change: relax the number with the human's
agreement, or `Waived` it with a rationale. An unmet requirement reported
plainly is a normal engineering outcome. An unmet requirement marked Verified
is a defect you have hidden.

## Run the gate and report what it says

```bash
/opt/hw-py/bin/python scripts/req_trace.py --gate
```

Report the number it prints, including the gaps. When coverage is 60%, say
60%. Do not describe a design as complete while the gate is failing; name what
is outstanding and what it would take to close it.

## What to check beyond the gate

The gate is structural. These are not, and they are where real problems hide:

* **Budget roll-ups reconcile.** Children's `BUDGET` values against the
  parent's. Do the arithmetic and show it.
* **Corners, not nominal.** Tolerance, temperature, supply. Evidence taken
  only at nominal does not close a requirement that has a range in it.
* **Electrical rule checks pass.** `kicad-cli sch erc` and `kicad-cli pcb drc`
  on the current files, not on a remembered earlier run.
* **The vision still holds.** Walk back up the tree to the `VIS-` entries and
  ask whether the thing you have designed is the thing the human described. A
  design can satisfy every requirement and still miss the point; that is worth
  saying out loud.

## Checks that must happen before the board is routed

These are verification too — they are the cheapest place to catch a defect,
and every one of them has been diagnosed as something else first, at a cost of
hours.

**Most of them now run as one command:**

```bash
sch-lint hw/probe.kicad_sch --gate --plan hw/block-diagram.yaml
pcb-lint hw/probe.kicad_pcb --gate
```

`pcb-lint` automates items 1, 2 and 4 below plus the keep-out check, ranks the
decoupling loops worst-first, and finds silkscreen on pads, unreadable
reference designators, overlapping courtyards and a signal layer with no
reference plane. `sch-lint` does the same for the drawing, and `--plan` binds
it to the architecture the human already agreed to. Both are read-only, both
run headless, and neither needs KiCad.

Run them, then item 3 — DRC on the placed, unrouted board — which nothing else
substitutes for. **`references/pcb-layout.md` next to this file has the full
workflow, the commands and the diagnosis stories.** The four that matter most:

1. **Net class widths against pad sizes.** A 1.20 mm track cannot enter a
   0.25 mm QFN pad and a router will not neck down. This presents as "180 of
   234 connections unroutable" with no stated reason, and gets blamed on
   density. Route at pad width, restore the carrying width afterwards.
2. **Net class clearances against pad pitch.** A 0.30 mm clearance against a
   VSON-10's 0.255 mm pad gap is violated *inside the footprint*, before a
   track exists.
3. **DRC on the placed, unrouted board.** It found 721 errors on one board,
   three of them real defects, long before there was anything to route.
   Placement errors are cheap; routed-board errors are not.
4. **`_ThermalVias` footprint variants.** The via array punches through to the
   other side and lands on whatever is opposite — 47 shorting pairs on one
   board, and it would have reached fabrication. Check the opposite side under
   every exposed pad.

Also: where a keep-out in a layout script mirrors a footprint dimension, read
it from the footprint rather than writing the number down. A keep-out at
6.60 mm guarding pads at 8.50 mm protects bare laminate and leaves the pads
exposed. `pcb-lint --keepout J5=6.60` checks a declared number against the real
footprint.

One fact worth holding before writing any board script: **net classes are not
in the `.kicad_pcb`.** They live in the sibling `.kicad_pro` under
`net_settings.classes`. A check that looks in the board file finds none and
reports the board clean.

And know which half of the toolchain you are in: **Konnect's schematic tools
are file-based; its PCB tools need a live KiCad.** When `check_kicad_ui`
reports `ipc_responsive: false`, scripted layout goes through KiCad's own
`pcbnew` Python API — the same object model, so still not text manipulation.

If the layout is going to be autorouted, read the freerouting section of the
reference first. Its CLI stop conditions do not work and it writes its output
only on a clean exit, so an unbounded run that you kill produces nothing at
all.

## Reporting

Publish the traceability output as an Artifact for anything the human will
share or act on — the coverage number, the table by level, and an explicit
list of what is not yet closed. Lead with the gaps, not the percentage.

**Draw it rather than tabulating it.** `hw-chart coverage` puts the gaps first
in every bar, which is the same rule in visual form; `hw-chart corners` shows
whether the evidence covers the corners or only nominal — a nominal-only result
has one bar and looks as thin as it is.

And put it where the human can actually see it. They are reviewing from
github.com while you work in a cloud VM, so the verification report belongs in
`docs/design/`, committed, with the ERC and DRC counts as numbers in the text.
Before claiming the design is done, open the review — see `hw-review`. A
verification report nobody has read is not a verification.
