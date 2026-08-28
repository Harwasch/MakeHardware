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

Write each concept as a plain build123d module under `concepts/`, defining
`PART`, plus optional `TITLE`, `NOTES`, `MATERIAL`:

```bash
/opt/hw-py/bin/python scripts/vision_board.py \
    concepts/concept_a.py concepts/concept_b.py --out build/vision
```

That writes shaded three-quarter, front and top views, an isometric line
drawing with hidden edges, and a `manifest.json` carrying the bounding box,
volume and an approximate mass for each concept.

**Always offer at least two concepts that differ in a way the human can name**
("softer vs. more instrument-like", "one-handed vs. two-handed"). A single
concept invites polite agreement; a pair forces a real preference, and the
reason they give you is worth more than the choice.

Then publish the set as an Artifact — renders, the numbers beside each one,
and the open questions — and ask the human to react. Iterate on the parameters
in the concept modules, not on prose.

These renders come from real geometry, so they cannot show something
unbuildable, and every picture is tied to a bounding box and a volume. Say so:
the human should know they are judging a real envelope, not a mood board. Do
not claim they are photorealistic product renders, because they are not.

## Leaving the stage

You are done when the human can point at one concept and the numbers beside it
without qualifying. Write what they agreed into `requirements/00-vision.sdoc`
as `VIS-*` entries in their words, then move to `hw-requirements`.
