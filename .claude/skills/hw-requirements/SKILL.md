---
name: hw-requirements
description: Author, decompose and validate hardware requirements as StrictDoc .sdoc files with full parent/child traceability. Use after the vision is agreed, whenever requirements need adding, splitting or renumbering, or when asked whether a design actually satisfies what was asked for.
---

# Requirements

Requirements live in `requirements/*.sdoc` and share the grammar in
`requirements/hardware.sgra`. They are plain text in git, so they diff and
review like code.

## The levels

The UID prefix carries the decomposition level. Nothing else does.

| Prefix | Level | Testable? | Refines |
|---|---|---|---|
| `VIS-` | vision intent, in the human's words | no, deliberately | nothing |
| `SYS-` | system requirement | yes | a `VIS-` |
| `ELE-` `MEC-` `FW-` `MFG-` | discipline requirement | yes | a `SYS-` |

Two rules make the tree mean something:

* **Every non-vision requirement Refines exactly one parent.** If you cannot
  name the parent, nobody asked for the requirement — raise it with the human
  instead of inventing a parent.
* **Every leaf carries EVIDENCE before it can be Verified.** A requirement with
  no evidence is a claim.

## Writing one

One "shall" per requirement, with a number and a unit wherever physics allows
one. "Low power" is not a requirement; "<= 40 uA in standby" is.

`RATIONALE` is the field that earns its keep. Write down *why this number*.
It is what you re-read when the number has to move, and it is what stops a
later session quietly relaxing a limit.

Use `BUDGET` when a parent's number is being divided among children, so the
roll-up can be checked: a 12 h parent against 40 uA + 180 uA children.

Multi-line fields need explicit block markers, and the body is rendered as
RST — a bare `SYS-*` will break the build on an unterminated emphasis span,
so write ``` ``SYS-`` ``` instead:

```
RATIONALE: >>>
Derived from SYS-001: a 900 mAh cell, 12 h active at 65 mA, and a 7-day
standby tail leaves 40 uA for the always-on rail.
<<<
```

## Validating

StrictDoc enforces referential integrity — duplicate UIDs and parents pointing
at nothing both fail the build:

```bash
/opt/hw-py/bin/strictdoc export requirements \
    --output-dir build/requirements --formats=html,json
```

What StrictDoc will not judge is whether the decomposition is any good. That
is `req_trace.py`, which finds orphans, undecomposed mid-level requirements,
leaves with no evidence, requirements with no design artefact linked, and
status/evidence mismatches:

```bash
/opt/hw-py/bin/python scripts/req_trace.py            # report
/opt/hw-py/bin/python scripts/req_trace.py --gate     # exit 1 on any gap
```

Run the gate before claiming a stage is complete.

## Validate the set, not just each requirement

Before starting design, check the things a per-requirement check cannot see:

* **Roll-up.** Do the children's budgets actually add up to the parent's? Say
  the arithmetic out loud.
* **Contradiction.** Two requirements that cannot both hold (an IP67 seal and
  a passive vent).
* **Over-constraint.** A requirement set with no feasible solution is more
  common than it sounds; if you cannot find one, say so now.
* **Missing verification.** Every leaf's `VERIFICATION` must be something this
  environment or the human can actually perform.

Report what you find to the human and get the numbers changed before design
starts, not after.
