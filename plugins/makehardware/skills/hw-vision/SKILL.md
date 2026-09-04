---
name: hw-vision
description: Run the vision stage of a hardware project - interview the human about what they actually want, then turn it into vision-board renders they can judge by eye. Use at the start of a new product, when the brief is still a sentence or a paragraph, or when someone says "I want to build X" without dimensions, budgets or constraints.
---

# Vision stage

The goal is a shared, concrete picture of the thing — not a requirements
document. Requirements come next, and they come out much better if this stage
did its job.

## Interview first, and go for the load-bearing questions

Start high level, but spend your questions where the answer changes the most
downstream. A question is high-leverage when different answers lead to
different architectures. Ask about those; assume sensible defaults for the rest
and say what you assumed.

The usual load-bearing set, roughly in order of leverage:

1. **Who holds it, and where.** Pocket, bench, rack, outdoors, inside another
   machine. This sets size, ingress protection, thermal path and connectors
   all at once.
2. **Power source.** Mains, battery, harvested, PoE. Battery immediately
   forces a capacity/runtime/size triangle you can put numbers on.
3. **The one number that must be true.** Runtime, accuracy, latency, weight,
   price. There is almost always exactly one the human really cares about.
4. **Volume and cost.** Ten units or ten thousand. This decides PCB layer
   count, connector choice, whether you can mould a housing at all.
5. **What it must not be.** The anti-goals are usually sharper than the goals
   and people give them up readily.
6. **Regulatory and environment.** Radio, mains isolation, medical, automotive,
   temperature range. Cheap to ask, ruinous to discover late.

Ask a few at a time and reflect back what you heard. Do not send a
questionnaire.

## Then show, do not tell

People judge a picture in a second and a paragraph in a minute, less
reliably. As soon as you can put numbers on an envelope, build the massing
model and render it.

A concept is one shape in one material, and `vision-board` is the right tool
for it — do not model an assembly at the vision stage. The moment the concept
is chosen and the envelope agreed, the model moves to `cad/` and becomes a
real assembly with labels, colours and joints: see `hw-cad`.

Write each concept as a plain build123d module under `concepts/`, defining
`PART`, plus optional `TITLE`, `NOTES`, `MATERIAL`, `RATIONALE`:

```bash
vision-board concepts/concept_a.py concepts/concept_b.py \
    --project "Thermal Probe" \
    --description "<the vision in the human's own words>"
```

That writes shaded three-quarter, front and top views, an isometric line
drawing with hidden edges, and a `manifest.json` carrying the bounding box,
volume and approximate mass for each concept — **into `docs/design/vision/`,
not `build/`** — plus `docs/design/vision.md`, the vision document.

The document is the point. It renders inline on github.com with every concept,
its numbers side by side, the styling proposals labelled as such and the open
questions at the end. You are almost certainly running in a cloud VM; the
human is looking at the repository in a browser, so a render under `build/` is
a render nobody sees. **Commit and push it before you ask anyone to look.**

## Build the thing they asked for, at the scope they asked for it

Two bare coil pads is not a product. If the human described something they
would hold, sell or install, the concept has to be recognisable as that thing
— an envelope, the interface they touch, the ports, roughly where the mass
is. A concept scoped to the sub-assembly you find most interesting invites a
polite yes to a question nobody asked, and there is nobody in a position to
catch it until much later.

When you genuinely cannot model the whole product yet, say what the model
covers and what it leaves out, in the document, above the picture.

**Always offer at least two concepts that differ in a way the human can name**
("softer vs. more instrument-like", "one-handed vs. two-handed"). A single
concept invites polite agreement; a pair forces a real preference, and the
reason they give you is worth more than the choice.

Then commit the document and the renders, and put it in front of the human —
see **`hw-review`** for the mechanism. Iterate on the parameters in the
concept modules, not on prose.

These renders come from real geometry, so they cannot show something
unbuildable, and every picture is tied to a bounding box and a volume. Say so:
the human should know they are judging a real envelope.

## Then style it, without losing the proportions

Geometry renders answer "is it the right size and shape". They do not answer
"does it look like something I want", which is about material, finish and
context.

Do them in this order so styling never quietly invents a different product:

1. **Render the geometry first.** That fixes the proportions and the numbers.
2. **Generate styling imagery from it** — see the **`hw-imagegen`** skill,
   which covers finding a backend in this environment and how to prompt for
   hardware. Prefer an image-*editing* model seeded with the geometry render,
   so the proportions survive.
3. **Label every generated image** *generated — styling only*, and keep the
   dimensioned line drawing beside it. Never let a generated image carry a
   number.

If no image backend is available, say so, ship the geometry renders, and tell
the human what enabling one would take. A board of dimensioned concepts is
still a good board.

## Leaving the stage

The vision stage is done when **a human has looked at the document and said
which concept, and that is recorded in the repository.** Not when the renders
exist. This stage has been reported complete on renders nobody saw, and the
plan, the requirements and the architecture were then all built on an
agreement that had never been made.

```bash
git add docs/design/vision.md docs/design/vision/ concepts/ && git commit && git push

review-gate open vision \
    --title "Vision and concept selection" \
    --summary "<what the two concepts are and how they differ>" \
    --artifact docs/design/vision.md --artifact docs/design/vision/ \
    --reference concepts/ \
    --question "Which concept, and what made you pick it?"
```

Then ask them directly — `AskUserQuestion`, with the github.com URL that
`review-gate` printed — and **block on the answer**. When they answer:

```bash
review-gate sign vision --approve --by <name> --note "<what they said>"
```

Record the *reason* they gave, not just the choice; it is worth more, and it
is what a later session re-reads when a number has to move. Write what they
agreed into `requirements/00-vision.sdoc` as `VIS-*` entries in their words,
commit the ledger, and move to `hw-planning`.

If they ask for changes, change the parameters, re-render, re-open the review
and ask again. That loop is the stage working.
