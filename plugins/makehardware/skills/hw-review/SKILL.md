---
name: hw-review
description: Get a human to actually look at and agree to the work, at every milestone - produce an artefact they can open on github.com, ask them directly with a link, and record the sign-off in the repo so a stage cannot be called done without it. Use before declaring the vision, the plan, the requirements, the architecture or any design stage complete, whenever an agreed artefact has changed since it was signed off, and any time you are about to build on something nobody has confirmed.
---

# Human review

The one rule: **an artefact the human has not seen is not a deliverable.**

This exists because the workflow used to state an exit condition for every
stage — "the human points at one concept", "the human has looked at the image
and agreed to it" — and had nothing that caused it to happen. So it did not:
concepts were rendered and never shown, the requirements export was generated
on every run and never mentioned, and the plan, the requirements and the
architecture were all built on top of an agreement that had never been made.
The cost was not the wasted renders. It was that four stages were reported
complete.

## Where the human actually is

You are almost certainly running in a **cloud VM**. The human is not at this
terminal, does not have KiCad, draw.io, build123d or your filesystem, and will
not run a command to see your work. What they have is **the repository on
github.com, in a browser**.

That constraint decides everything about what a review artefact is:

| You made | They can review | So commit |
|---|---|---|
| a KiCad schematic | nothing | a **PDF** — `kicad-cli sch export pdf` — and the **`sch-lint --svg` overlay**, which is 340 elements against the plot's 60,000 and shows what is wrong |
| a KiCad board | nothing | **PDF** layer plots, a **PNG** 3D render top and bottom, and the **`pcb-lint --svg`** overlay with the decoupling loops on it |
| a build123d model | nothing | **`cad-export`**: renders, section, exploded view, an **`.stl`** GitHub shows in its own 3D viewer, and a **`.glb`** the review page orbits |
| a `.drawio` diagram | nothing | the **SVG** rendered from the same spec |
| a StrictDoc tree | nothing | the **SVG** requirements map — `req-trace --map` |
| a SPICE run | nothing | **`hw-chart corners`** or **`hw-chart bode`**, with the numbers on the chart |
| a `plan.yaml` | badly | `docs/plan.md` and `docs/plan.svg` — `plan-render` |
| a budget, a BOM, a coverage report | badly | **`hw-chart`** — `budget`, `waterfall`, `coverage` |

Commit the source too, so anyone who wants to open it in the real application
can. But the review is over the thing that renders in a browser. **If nothing
in a review renders in a browser, it is a download, not a review**, and
`review-gate` will tell you so.

GitHub renders `.md`, `.png`, `.jpg`, `.svg` and `.pdf` inline. It does not
render `.drawio`, `.kicad_*`, `.step` or `.html`.

## The four milestones, at a minimum

Never skip these. Each one is an agreement everything after it rests on.

| id | Stage | The artefact that renders | Ask them |
|---|---|---|---|
| `vision` | 1 | `docs/design/vision.md` + the renders under `docs/design/vision/` | which concept, and why |
| `plan` | 2 | `docs/plan.md` (scope and task descriptions) + `docs/plan.svg` (the dependency Gantt) | is this all the work, is the order right |
| `requirements` | 3 | `docs/design/requirements-map.svg` + the StrictDoc HTML export | are the numbers right, is anything missing |
| `architecture` | 4 | `docs/design/block-diagram.svg` + the power budget | is a rail missing, is a bus on the wrong controller |

Then **one per large design stage** — schematic capture, PCB layout, the
enclosure, each simulation campaign — using the same mechanism with an id of
your choosing (`schematic`, `layout`, `enclosure`, `thermal`).

## The loop

### 1. Produce the artefact and commit it

Generate it, look at it yourself first, then `git add` and **push**. A link to
an uncommitted file is a 404, and that is the fastest way to waste the
human's time. `review-gate open` checks this and names anything not yet
committed.

### 2. Open the review

```bash
review-gate open vision \
    --title "Vision and concept selection" \
    --summary "Two concepts: A is one-handed with the probe on a lead, B is
               bench-shaped with a bigger display. Numbers under each." \
    --artifact docs/design/vision.md \
    --artifact docs/design/vision/ \
    --reference concepts/ \
    --question "Which concept, and what made you pick it?" \
    --question "Is 164 mm too long for a coat pocket?"
```

That writes `docs/review/vision.md` — a page with the images inline, the
questions, and links to everything — records the digest of each artefact in
`docs/review/reviews.yaml`, and prints the github.com URLs.

**`--artifact` is the agreement; `--reference` is a link.** A tracked artefact
that changes after sign-off makes the review stale. Use `--reference` for
sources that legitimately churn — `plan.yaml`, a live `.kicad_sch`, the
`concepts/` modules — so the review does not go stale on every ordinary edit.
Choose the tracked artefact so that *what the human agreed to* is what makes
it stale: `docs/plan.md` carries no statuses precisely so the plan review
survives a week of progress and breaks when the scope changes.

Commit the packet and the ledger.

### 2b. Check the page before you send it

```bash
review-artifact --check     # exits 1, and names anything it cannot show
```

An export that failed leaves no file, and a render that is too big cannot be
embedded. Both are reported on the page rather than silently dropped — but a
page with "not shown here" boxes on it is not a review, and the human is the
most expensive place to discover that. Fix the export, then publish.

### 2c. Publish the page, and lead the request with it

```bash
review-artifact                      # writes docs/review/artifact.html
review-artifact --check              # and names anything it could not show
# publish it with the Artifact tool, then:
review-artifact --url <the artifact URL>
```

**The published page is the review; the repository is the archive.** They are
not the same surface and neither replaces the other:

* On the **page**, a schematic sheet zooms, a 3D assembly orbits, a BOM sorts
  by price and every value is one hover from its exact number. That is the
  difference between a picture of a schematic and a schematic.
* In the **repository** are the committed SVGs, PNGs, PDFs and `.stl` that
  render on github.com — what the human still has tomorrow, and what a
  reviewer with no session open can read.

So: commit everything, publish the page, and put the **page** URL in the
question with the repository link beneath it. Recording the URL matters — the
next session updates the same page instead of leaving a trail of orphans.

### 3. Ask them, with the link, and block

Use whatever tool this session has for putting a direct question to the human
— in Claude Code that is **`AskUserQuestion`**. Not a paragraph at the end of
a message they may not read: a question that stops and waits.

The question must carry:

* **the github.com URL of the review packet**, so one click gets them there;
* what you are asking, in one line;
* options that are real decisions, not "yes / no".

```
Vision is ready for review — two concepts, numbers under each.
https://claude.ai/.../artifact/...        <- the page: zoom, orbit, sort
https://github.com/<owner>/<repo>/blob/<branch>/docs/review/vision.md

  [ Concept A — the wand ]  [ Concept B — the instrument ]
  [ Neither, here's why  ]
```

`review-gate urls vision` prints the links; `review-gate open` prints the
whole request ready to use.

Then **stop**. Do not start the next stage. If there is genuinely independent
work that does not depend on the answer, do that and come back — but do not
build anything on an unanswered question, and do not answer it yourself.

### 4. Record what they said

```bash
review-gate sign vision --approve --by harrison \
    --note "Concept B. The instrument look reads as trustworthy in a
            commercial kitchen, which is where these get bought."

review-gate sign vision --changes "Too tall. Wants it under 140 mm and the
                                   display readable with gloves on."
```

Record it **in their words**. The reason they gave is worth more than the
choice, and it is what a later session re-reads when a number has to move.
Then commit — the ledger is the record, and a decision that lives only in a
chat transcript is a decision you will have to ask for again.

On `--changes`: fix it, re-run `review-gate open`, and ask again. A review is
a loop, not a form.

### 5. Only now is the stage done

```bash
review-gate check --gate     # exit 1 while any milestone is open or stale
plan-render --check          # a done chunk with an unsigned review fails here
```

Declare a chunk `done` in `plan.yaml` with a `review:` field naming its
review, and `plan-render --check` will refuse the claim until the sign-off
exists. That is the `req-trace --gate` discipline — evidence before a claim —
applied to agreement.

## Staleness is not bureaucracy

`review-gate` re-hashes every tracked artefact. If one changed after sign-off,
the review reads **stale** and the gate fails.

This is the case the whole mechanism exists for: the human agreed to a block
diagram, you changed a rail two sessions later, and everything downstream is
now resting on an agreement about a different diagram. Re-open it, say what
changed and why, and ask again. It is a short conversation and it costs
nothing compared to the alternative.

## Reviewing continuously, not only at milestones

Milestones are the floor, not the ceiling. Also go back to the human when:

* **you had to guess.** A guess you did not surface is a defect with a delay
  on it. Ask, and if you must proceed, say plainly what you assumed.
* **you are about to do something expensive** — order parts, generate fab
  output, commit to a package or a process.
* **a number moved after it was agreed.** Requirements that change silently
  are how a project ends up building something nobody asked for.
* **two readings of the brief lead to different hardware.** That is not a
  detail to resolve with a default.
* **the work turned out much bigger or smaller than the plan said.** The plan
  is an agreement too.

Between milestones, keep the generated artefacts current and committed —
`plan-render`, `block-diagram`, `req-trace --map` all re-render from their
specs in one command. A repository whose pictures are current is one the human
can review whenever they feel like it, which is worth more than any scheduled
checkpoint.

## What a good review request looks like

Short, specific, and answerable without opening a terminal:

* **Lead with the decision you need**, not with what you did.
* **Say what changed since last time**, if there was a last time.
* **Name the thing you are least sure about.** Reviewers find what you point
  at; a request that projects total confidence gets a rubber stamp, and a
  rubber stamp is not an agreement.
* **Offer real alternatives with their consequences.** "A is 12 g lighter, B
  is £4 cheaper at 1k" is a decision. "Does this look OK?" is not.
* **Never ask them to review something you have not looked at yourself.**
  Open the PDF. Look at the render. Open the page and use it — zoom a sheet,
  orbit the model, sort the table. Half of what a review would catch, you will
  catch first, and a control that does not work is worse than one that is not
  there.
* **Show, do not describe.** If a number can be plotted, plot it. `hw-chart`
  covers the standard ones. A paragraph explaining which rail is tight is a
  paragraph that a bar chart would have made unnecessary.

## What this is not

It is not a status update, and it is not a request for approval of your
process. It is a specific question about a specific artefact, and the answer
changes what you do next. If the answer would not change anything, do not ask
it — say what you did and carry on.
