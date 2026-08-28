# The workflow

Five stages. The first two are conversations with a human; the last three are
a loop. Each stage has an exit condition you can check, which is what stops the
agent declaring victory early.

```
  1 VISION ─────► 2 REQUIREMENTS ─────► 3 DESIGN ─────► 4 SIMULATE ─────► 5 VERIFY
   interview        decompose &           schematic       ngspice           evidence
   + renders        validate              + CAD           FEA               + gate
        ▲                 ▲                   ▲               │                 │
        │                 │                   └───────────────┘                 │
        │                 └───────── numbers must move ────────────────────────┤
        └───────────────── the thing is not what they meant ────────────────────┘
```

## 1. Vision — interview, then show

Skill: `hw-vision`

The human arrives with a sentence. The agent asks the questions where
different answers lead to different architectures — where it is held and
where, power source, the one number that must be true, volume and cost, the
anti-goals, regulatory. A few at a time, reflecting back what it heard.

Then it stops talking and renders. Concepts are build123d modules under
`concepts/`; `scripts/vision_board.py` turns them into shaded three-quarter,
front and top views plus an isometric line drawing, each with its bounding
box, volume and approximate mass. Those go into an Artifact the human reacts
to.

**Always at least two concepts that differ in a nameable way.** One concept
invites polite agreement; a pair forces a real preference, and the reason
given is worth more than the choice.

Because the renders come from real geometry, they cannot show something
unbuildable, and "make it 3 mm thinner" is a parameter change and a re-render,
not a redraw.

> **Exit:** the human points at one concept and its numbers without
> qualifying. Agreed intent is written to `requirements/00-vision.sdoc` as
> `VIS-*` entries, in their words.

## 2. Requirements — decompose, then validate

Skill: `hw-requirements`

`VIS-*` intent becomes testable `SYS-*` requirements, which decompose into
`ELE-` / `MEC-` / `FW-` / `MFG-` requirements. Every non-vision requirement
Refines exactly one parent; if the agent cannot name the parent, nobody asked
for the requirement and it raises that instead of inventing one.

Validation is two layers, because they catch different things:

* **StrictDoc** enforces referential integrity — duplicate UIDs and parents
  pointing at nothing both fail the build outright.
* **`scripts/req_trace.py`** judges the decomposition: orphans, undecomposed
  mid-level requirements, leaves with no evidence, requirements with no design
  artefact linked, status/evidence mismatches.

Then the agent checks what neither tool can see: do the children's budgets add
up to the parent's, are any two requirements contradictory, is the set
over-constrained, can every leaf's verification method actually be performed
here.

> **Exit:** `req_trace.py` reports no structural gaps other than
> not-yet-verified leaves, and the human has agreed any numbers that moved.

## 3. Design sprint

Skills: Konnect's `kicad-schematic`, `kicad-pcb`, `kicad-library` (installed by
`konnect init`), plus build123d for mechanical.

Electrical work is file-based by default — Konnect's S-expression engine for
schematics, `kicad-cli` for ERC/DRC/netlist/gerbers/STEP. Live board editing
escalates to a running KiCad via `hw-kicad-up`, which brings up Xvfb and opens
the project so Konnect's IPC tools work.

Mechanical work is build123d modules under `cad/`, exporting STEP for the
KiCad 3D view and STL for meshing.

Every artefact gets a `File` relation from the requirement it realises. That
link is what makes stage 5 possible, and it is much cheaper to add now.

## 4. Simulation

Skill: `hw-simulation`

ngspice through the `spice` MCP server for electrical; gmsh + CalculiX for
thermal and structural. Measurements come back as parsed numbers, not plots.

Three rules that keep this honest:

* **Cross-check against closed form** wherever one exists. If the simulator
  and the arithmetic disagree, the deck is wrong.
* **Read the `observations` field.** ngspice will print `singular matrix` once,
  deep in a log, then finish and write plausible numbers anyway.
* **Sweep corners.** Tolerance, temperature, supply. A design that only works
  at nominal is not a design.

A failed simulation loops back to stage 3. A simulation that cannot meet the
number loops back to stage 2 — the requirement moves, with the human's
agreement, and the `RATIONALE` says why.

## 5. Verification

Skill: `hw-verification`

A requirement becomes `Verified` only with all four of: a `VERIFICATION`
method, an `EVIDENCE` pointer someone can go and look at, a `File` relation to
the artefact, and evidence that shows the number being met *at the corners*.

```bash
/opt/hw-py/bin/python scripts/req_trace.py --gate
```

The gate exits 1 while gaps remain. Report the number it prints, gaps first.
Never set `Verified` to make the gate pass — an unmet requirement reported
plainly is a normal engineering outcome; one marked Verified is a hidden
defect.

The last check is the one no tool performs: walk back up to the `VIS-` entries
and ask whether the thing designed is the thing the human described. A design
can satisfy every requirement and still miss the point.

> **Exit:** gate passes, ERC and DRC are clean on the current files, budget
> roll-ups reconcile, and the vision still holds.

## Why the loop runs in this order

The expensive mistake in hardware is discovering in stage 4 that stage 2 asked
for something impossible. Two things are arranged to catch that early: vision
renders are geometry (so an envelope that cannot hold the battery shows up
before any schematic exists), and requirements carry `BUDGET` numbers that must
roll up (so an over-constrained set is arithmetic, not a surprise).
