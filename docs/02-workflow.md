# The workflow

Six stages. The first three are agreements with a human; the last three are a
loop. Each stage has an exit condition you can check, which is what stops the
agent declaring victory early.

```
1 VISION ─► 2 PLAN ─► 3 REQUIREMENTS ─► 4 DESIGN ─► 5 SIMULATE ─► 6 VERIFY
 interview   chunks &   decompose &      schematic   ngspice        evidence
 + renders   deps       validate         + CAD       FEA            + gate
     ▲          ▲            ▲               ▲           │             │
     │          │            │               └───────────┘             │
     │          │            └────── numbers must move ────────────────┤
     └──────────┴───── the thing is not what they meant ───────────────┘
```

Two things run across all six: **sourcing** (`hw-sourcing`) whenever a part is
picked, and **documentation** (`hw-documentation`) whenever a number comes from
outside or a decision is made.

## 1. Vision — interview, then show

Skill: `hw-vision`

The human arrives with a sentence. The agent asks the questions where different
answers lead to different architectures — where it is held and where, power
source, the one number that must be true, volume and cost, the anti-goals,
regulatory. A few at a time, reflecting back what it heard.

Then it stops talking and renders. Concepts are build123d modules under
`concepts/`; `vision-board` turns them into shaded three-quarter, front and top
views plus an isometric line drawing, each with its bounding box, volume and
approximate mass.

**Geometry first, then styling.** The geometry render fixes proportions and
numbers. Styling imagery — material, finish, colour, context — comes from the
Hugging Face connector's image spaces, preferably `FLUX.1-Kontext-Dev` seeded
with the geometry render so the proportions survive. Generated images are
labelled as styling proposals and never carry a number.

**Always at least two concepts that differ in a nameable way.** One concept
invites polite agreement; a pair forces a real preference, and the reason given
is worth more than the choice.

> **Exit:** the human points at one concept and its numbers without qualifying.
> Agreed intent goes to `requirements/00-vision.sdoc` as `VIS-*` entries, in
> their words.

## 2. Plan — what work exists, and in what order

Skill: `hw-planning`

Before any requirement is written, agree the shape of the work. `plan.yaml`
holds session-sized chunks with explicit `depends_on` edges;
`plan-render` schedules them by longest path and draws a dependency Gantt into
the README, with the critical path outlined and each chunk's status shown.

This is where the project's disciplines get decided. A machined bracket has
`mechanical` and nothing else; a sensor node has mechanical, electrical,
firmware and test. Only the lanes that exist go in the plan.

The plan is a checkpoint, and the two real questions are: **is this all the
work** (test, documentation and manufacturing are what people forget), and
**is the order right** (the human usually knows a constraint you do not).

> **Exit:** `plan-render --check` passes, and the human has agreed the chunk
> list and the ordering.

## 3. Requirements — decompose, then validate

Skill: `hw-requirements`

`VIS-*` intent becomes testable `SYS-*` requirements, which decompose into
`ELE-` / `MEC-` / `FW-` / `MFG-` requirements. Every non-vision requirement
Refines exactly one parent; if the agent cannot name the parent, nobody asked
for the requirement and it raises that instead of inventing one.

Validation is two layers, because they catch different things:

* **StrictDoc** enforces referential integrity — duplicate UIDs and parents
  pointing at nothing both fail the build outright.
* **`req-trace`** judges the decomposition: orphans, undecomposed mid-level
  requirements, leaves with no evidence, requirements with no design artefact
  linked, status/evidence mismatches.

Then the agent checks what neither tool can see: do the children's budgets add
up to the parent's, are any two requirements contradictory, is the set
over-constrained, can every leaf's verification method actually be performed.

> **Exit:** `req-trace` reports no structural gaps other than not-yet-verified
> leaves, and the human has agreed any numbers that moved.

## 4. Design sprint

Skills: Konnect's `kicad-schematic`, `kicad-pcb`, `kicad-library`, plus
build123d for mechanical and `hw-sourcing` for every part choice.

Electrical work is file-based by default — Konnect's S-expression engine for
schematics, `kicad-cli` for ERC/DRC/netlist/gerbers/STEP. Live board editing
escalates to a running KiCad via `hw-kicad-up`. Mechanical work is build123d
modules under `cad/`.

Every artefact gets a `File` relation from the requirement it realises, and
every decision that constrains something downstream gets an ADR in
`docs/design/`. Both are much cheaper to add now than to reconstruct later.

## 5. Simulation

Skill: `hw-simulation`

ngspice through the `spice` MCP server for electrical; gmsh + CalculiX for
thermal and structural. Measurements come back as parsed numbers, not plots.

Three rules that keep this honest: **cross-check against closed form** wherever
one exists; **read the `observations` field**, because ngspice will print
`singular matrix` once and then write plausible numbers anyway; and **sweep
corners** — tolerance, temperature, supply.

A failed simulation loops back to stage 4. A simulation that cannot meet the
number loops back to stage 3 — the requirement moves, with the human's
agreement, and the `RATIONALE` says why.

## 6. Verification

Skill: `hw-verification`

A requirement becomes `Verified` only with all four of: a `VERIFICATION`
method, an `EVIDENCE` pointer someone can go and look at, a `File` relation to
the artefact, and evidence that shows the number being met *at the corners*.

```bash
req-trace --gate    # exits 1 while gaps remain
```

Report the number it prints, gaps first. Never set `Verified` to make the gate
pass — an unmet requirement reported plainly is a normal engineering outcome;
one marked Verified is a hidden defect.

The last check is the one no tool performs: walk back up to the `VIS-` entries
and ask whether the thing designed is the thing the human described.

> **Exit:** gate passes, ERC and DRC are clean on the current files, budget
> roll-ups reconcile, and the vision still holds.

## Documentation, throughout

Skill: `hw-documentation`

Three kinds, kept apart because they have different owners and failure modes:

* **`docs/reference/`** — external material: datasheets, app notes, standards.
  Never edited, always recorded in `manifest.yaml` with its revision and
  retrieval date. When the environment cannot fetch one, it is marked blocked
  and the human is asked — a number from memory instead of a datasheet is
  exactly the confident wrong answer that gets a board fabricated wrong.
* **`docs/design/`** — how and why we built it. ADRs written as the work
  happens, with the Consequences section filled in honestly.
* **`docs/user/`** — manuals, spec sheet, safety. Written late, stubbed early:
  a product whose spec sheet cannot be filled in usually has a requirements
  gap.

## Why the loop runs in this order

The expensive mistake in hardware is discovering in stage 5 that stage 3 asked
for something impossible. Three things are arranged to catch that early: vision
renders are geometry, so an envelope that cannot hold the battery shows up
before any schematic exists; the plan makes cross-discipline dependencies
explicit before anyone commits to a part; and requirements carry `BUDGET`
numbers that must roll up, so an over-constrained set is arithmetic rather than
a surprise.
