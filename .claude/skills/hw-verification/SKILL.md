---
name: hw-verification
description: Close out hardware requirements against evidence and report honest coverage. Use at the end of a design sprint, before claiming a design is done, or whenever asked "does this meet the requirements" or "what is left".
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

## Reporting

Publish the traceability output as an Artifact for anything the human will
share or act on — the coverage number, the table by level, and an explicit
list of what is not yet closed. Lead with the gaps, not the percentage.
