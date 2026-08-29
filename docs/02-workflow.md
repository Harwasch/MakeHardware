# The workflow

Seven stages. The first four are agreements with a human; the last three are a
loop. Each stage has an exit condition you can check, which is what stops the
agent declaring victory early.

```
1 VISION ─► 2 PLAN ─► 3 REQS ─► 4 ARCHITECTURE ─► 5 DESIGN ─► 6 SIMULATE ─► 7 VERIFY
 interview   chunks &  decompose  block diagram    schematic   ngspice       evidence
 + renders   deps      + validate  + power budget   + CAD       FEA           + gate
     ▲          ▲          ▲            ▲              ▲           │            │
     │          │          │            │              └───────────┘            │
     │          │          │            └──── a rail is short ──────┤            │
     │          │          └────────── numbers must move ───────────┤            │
     └──────────┴──────── the thing is not what they meant ─────────────────────┘
```

Five things run across all seven: **review** (`hw-review`) at every milestone
and whenever you had to guess, **sourcing** (`hw-sourcing`) whenever a part is
picked, **documentation** (`hw-documentation`) whenever a number comes from
outside or a decision is made, **imagery** (`hw-imagegen`) wherever a picture
helps, and **friction capture** (`hw-retro`) whenever the human corrects you or
a task takes far more loops than it should.

## The exit conditions have a mechanism

Every stage below states an exit condition, and most of them end in "the human
agreed". That used to be a sentence with nothing behind it, and the predictable
happened: concepts were rendered and never shown, the requirements export was
generated on every run and never mentioned, and four stages in a row were
reported complete on agreements that had never been made. The cost was not the
wasted renders — it was that the plan, the requirements and the architecture
were all built on top of them.

So agreement is now an artefact, like evidence:

```bash
review-gate open <milestone> --artifact <what renders> --question "..."
#   ... ask the human directly, with the github.com link, and block ...
review-gate sign <milestone> --approve --by <name> --note "<their words>"
review-gate check --gate        # exit 1 while any milestone is open or stale
```

`docs/review/reviews.yaml` is the record, and it carries the digest of every
artefact as it stood when the human looked at it — change one afterwards and
the review reads **stale** and the gate fails. A chunk in `plan.yaml` that
names a `review:` cannot be marked `done` until that review is signed off;
`plan-render --check` refuses it. Same discipline as `req-trace --gate`
applies to evidence, applied to agreement.

**The one rule: an artefact the human has not seen is not a deliverable.**

### Which means the artefact has to be one they can see

The agent is usually working in a **cloud VM**. The human is not at that
terminal and does not have KiCad, draw.io or build123d — what they have is the
repository on **github.com, in a browser**. So every review produces something
that renders there, committed and pushed, alongside the source:

| Stage | What the human opens |
|---|---|
| 1 Vision | `docs/design/vision.md` — concepts, renders, numbers, open questions |
| 2 Plan | `docs/plan.md` (scope and task descriptions) + `docs/plan.svg` (the dependency Gantt) |
| 3 Requirements | `docs/design/requirements-map.svg` — the tree, its statuses and its gaps |
| 4 Architecture | `docs/design/block-diagram.svg` + the power budget as text |
| 5 Design | a schematic **PDF**, board layer **PDF**s and 3D **PNG**s, CAD renders |
| 6 Simulation | the numbers in a markdown table, failing corner first |
| 7 Verification | the coverage number and the gaps, in `docs/design/` |

Diagrams are generated as **draw.io** files from their spec, with an SVG
rendered from the same model, so the editable file and the review image cannot
disagree. GitHub renders the SVG; draw.io opens the other.

`hw-review` covers the loop and `hw-review/references/exports.md` has the
export commands per artefact type.

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

The renders and `docs/design/vision.md` go under `docs/design/`, committed —
not `build/`, which nobody can see.

> **Exit:** `review-gate check vision --gate` passes — the human has looked at
> the document and pointed at one concept and its numbers without qualifying,
> and that is signed off in `docs/review/reviews.yaml`. Agreed intent goes to
> `requirements/00-vision.sdoc` as `VIS-*` entries, in their words.

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

`plan-render` writes the Gantt (`docs/plan.svg`), the editable graph
(`docs/plan.drawio`) and `docs/plan.md` — the scope and every chunk's
description, with no statuses in it, so an agreement survives a week of
ordinary progress and breaks the moment the work is redefined. `--check` also
refuses a `done` chunk whose declared `outputs` are not on disk, which is the
bookkeeping error that quietly makes a status report wrong.

> **Exit:** `plan-render --check` passes, and `review-gate check plan --gate`
> passes — the human has agreed the chunk list and the ordering.

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

`req-trace --map` draws the tree — one column per level, an arrow to every
requirement that refines another, statuses on the nodes and the gate's
findings in red. That is what a human can actually review; a list of UIDs is
how a gap survives a review.

> **Exit:** `req-trace` reports no structural gaps other than not-yet-verified
> leaves, and `review-gate check requirements --gate` passes — the human has
> agreed any numbers that moved.

## 4. Architecture — the block diagram

Skill: `hw-block-diagram`

The last agreement before anything is wired. Requirements say what the thing
must do; the block diagram says what parts will do it, what powers them, and
what talks to what. Three questions, all expensive to answer later:

* **What major parts exist?** ICs, regulators, connectors, modules — not passives.
* **What powers each?** The full power tree, with a current budget per rail.
* **What talks to what?** The data buses, with their controllers.

`hw/block-diagram.yaml` is the source of truth and the only file edited by hand.
`block-diagram` renders it to `hw/block-diagram.drawio` — editable in draw.io,
and positions moved there are kept on the next run — and to
`docs/design/block-diagram.svg`, which renders inline on GitHub for review.
Generating both from one spec is what stops the picture and the architecture
disagreeing, which is the usual fate of a block diagram.

The budget is the part that earns its keep. Each rail declares what its source
can deliver; each block declares what it draws; the tool sums the loads,
including everything on the rails derived from it. `block-diagram --check`
exits 1 when a rail is over, and names the contributors largest first.
Converter efficiency is deliberately not modelled — this is a headroom check,
not an energy model.

> **Exit:** `review-gate check architecture --gate` passes — the human has
> looked at the image and agreed to it; every block has a part number or an
> explicit TBD with a chunk that will resolve it; every current traces to a
> datasheet in `docs/reference/`; `block-diagram --check` passes.

## 5. Design sprint

Skills: Konnect's `kicad-schematic`, `kicad-pcb`, `kicad-library`, plus
build123d for mechanical and `hw-sourcing` for every part choice.

Electrical work is file-based by default — Konnect's S-expression engine for
schematics, `kicad-cli` for ERC/DRC/netlist/gerbers/STEP. Live board editing
escalates to a running KiCad via `hw-kicad-up`. Mechanical work is build123d
modules under `cad/`.

Every artefact gets a `File` relation from the requirement it realises, and
every decision that constrains something downstream gets an ADR in
`docs/design/`. Both are much cheaper to add now than to reconstruct later.

**Each large design stage ends in a review**, on the same mechanism as the
first four. A `.kicad_sch` or a `.step` is a download, not a review, so export
first: `kicad-cli sch export pdf`, `kicad-cli pcb export pdf` for the layer
plots and `kicad-cli pcb render` for both sides, `vision-board` for a CAD
module. Commit them under `docs/design/`, then
`review-gate open schematic --artifact docs/design/schematic.pdf`. The ERC and
DRC counts go in the request as numbers, not as an attachment nobody opens.

Before the board is routed, run the pre-route checks in
`hw-verification/references/pcb-layout.md`. Net class widths against pad
sizes, clearances against pad pitch, DRC on the placed board, and the
opposite side under every thermal-via footprint. All four are arithmetic, all
four take a minute, and every one of them has cost hours by being diagnosed
as board density instead.

## 6. Simulation

Skill: `hw-simulation`

ngspice through the `spice` MCP server for electrical; gmsh + CalculiX for
thermal and structural. Measurements come back as parsed numbers, not plots.

Four rules that keep this honest: **cross-check against closed form** wherever
one exists; **read the `observations` field**, because ngspice will print
`singular matrix` once and then write plausible numbers anyway; **sweep
corners** — tolerance, temperature, supply; and **before concluding an
approach cannot work, list the design levers you did not vary**. A negative
result from one configuration is a result about that configuration, and the
levers usually left fixed are the geometry and topology ones that corner
sweeping does not touch.

A failed simulation loops back to stage 4. A simulation that cannot meet the
number loops back to stage 3 — the requirement moves, with the human's
agreement, and the `RATIONALE` says why.

## 7. Verification

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
> roll-ups reconcile, the vision still holds, and `review-gate check --gate`
> is clear — including any milestone that went **stale** because an agreed
> artefact changed underneath it.

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

## Closing the loop back onto the toolbox

Skill: `hw-retro`

During the work, avoidable friction goes into `docs/design/friction-log.md` —
three lines, one of which names the MakeHardware file that should have
prevented it. At a milestone, `/hw-retro` synthesises those with plan estimates
against actuals and requirements that moved after being agreed, into
`docs/design/retro.md`.

The rule that makes it useful: **every entry names a file and an edit.** An
observation like "communication could be better" improves nothing. "Fill in the
board-to-wire row of `hw-sourcing/references/connectors.md`, because connectors
were relitigated three times" is a change someone can make. Those become issues
on MakeHardware, and project N makes project N+1 better.

## Review, throughout

Skill: `hw-review`

The four milestones are the floor, not the ceiling. Go back to the human as
well whenever **you had to guess** (a guess you did not surface is a defect
with a delay on it), whenever you are about to do something **expensive or
irreversible** — order parts, generate fabrication output, commit to a process
— whenever **a number moved after it was agreed**, and whenever two readings
of the brief would lead to different hardware.

Between milestones the cheap thing is to keep the generated artefacts current
and committed: `plan-render`, `block-diagram` and `req-trace --map` each
re-render from their spec in one command. A repository whose pictures are
current is one the human can review whenever they feel like it, which is worth
more than any scheduled checkpoint.

## Why the loop runs in this order

The expensive mistake in hardware is discovering in stage 6 that stage 3 asked
for something impossible. The more expensive one is discovering in stage 6
that stage 1 was never agreed. Five things are arranged to catch those early:
every stage's agreement is a committed record rather than a sentence, so a
stage cannot be reported complete without one; and beyond that, vision
renders are geometry, so an envelope that cannot hold the battery shows up
before any schematic exists; the plan makes cross-discipline dependencies
explicit before anyone commits to a part; requirements carry `BUDGET` numbers
that must roll up, so an over-constrained set is arithmetic rather than a
surprise; and the block diagram turns the power tree into arithmetic too, one
stage before the schematic that would otherwise be the first place a short rail
shows up.

The block diagram sits where it does for a specific reason. It is the cheapest
artefact that can be wrong in a way you can see: a page of boxes takes an hour
to write and a minute to read, and a human reviewing it will catch a missing
rail or a bus on the wrong controller far faster than they would reading a
schematic. Putting it after requirements means it can be checked against them;
putting it before capture means the correction costs an edit rather than a
re-route.
