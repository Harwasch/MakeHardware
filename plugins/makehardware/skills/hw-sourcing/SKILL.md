---
name: hw-sourcing
description: Select components and suppliers according to house practice - how to choose a part, when to prefer a known family over an optimal one, and which brands and series this shop standardises on. Use whenever a part needs picking, a BOM line needs filling, an alternate needs qualifying, or someone asks "what connector should I use".
---

# Sourcing and component selection

House practice lives in `references/` next to this file. Read the relevant one
before picking a part — they encode decisions already made and paid for.

| File | Covers |
|---|---|
| `references/philosophy.md` | How to make a selection decision at all |
| `references/connectors.md` | Connector families this shop standardises on |
| `references/passives.md` | Resistors, capacitors, inductors, tolerances |

These are living files. When the human overrules a choice, **write the new
preference into the reference file in the same session**, with the reason. That
is how this gets better; a correction that only lives in a chat transcript is a
correction you will make again.

## Finding candidates vs. choosing between them

**kicad-happy finds; this skill decides.** Use its `digikey`, `mouser`, `lcsc`
and `element14` skills for real stock, pricing and parametric search, and its
`datasheets` skill to pull specs out of a PDF. Then apply the philosophy below
to pick between what they return. Do not do parametric search from memory when
a distributor skill can answer it.

## Read datasheets locally, and do not fan out

Datasheet research is unusually token-heavy: every PDF arrives as one large
blob, and a parametric comparison wants several of them. Two rules keep that
from consuming a session's whole budget.

**Fetch and extract locally rather than pulling a PDF through an agent's
context.** `WebFetch` cannot read most datasheets — it comes back saying the
specifications are "embedded within the compressed PDF content stream and are
not directly readable". The environment installs `pypdf` and `poppler-utils`
for exactly this:

```bash
curl -sL -o docs/reference/lmg2610-ds.pdf https://www.ti.com/lit/ds/symlink/lmg2610.pdf

/opt/hw-py/bin/python -c '
from pypdf import PdfReader
r = PdfReader("docs/reference/lmg2610-ds.pdf")
text = "\n".join(p.extract_text() or "" for p in r.pages)
open("build/lmg2610.txt", "w").write(text)
print(len(r.pages), "pages,", len(text), "chars")'

grep -n -i -E -A4 "quiescent|thermal resistance|R_DS" build/lmg2610.txt
```

Then read the section you need, not the document. `pdftotext -layout` is the
fallback when `pypdf` mangles a table.

**Serialise the research, or cap it at two or three concurrent agents.** Seven
parallel research agents each fetching and parsing multi-megabyte datasheets
exhausted a five-hour account limit before all but one had returned, taking
out the other six and every verification agent behind them. The work was not
wrong, it was sized wrong. Extract locally as above and fan out over the
*extracted text* if you fan out at all — never over PDF fetches.

Every datasheet you fetch is recorded in `docs/reference/manifest.yaml` with
its revision and retrieval date; see `hw-documentation`.

## The short version

Selection is a constraint problem with a tie-break, not an optimisation:

1. **Filter on the hard constraints** — the electrical and mechanical numbers
   the requirement actually demands, plus temperature range and package.
2. **Filter on availability** — in stock, in quantity, at more than one
   distributor, not marked NRND or last-time-buy. A perfect part you cannot buy
   is not a candidate.
3. **Prefer a family already on the BOM.** Second-sourcing an existing part
   beats introducing a new one, even when the new one is slightly better.
4. **Then** tie-break on cost, footprint size, and datasheet quality.

Never lead with cost. A part chosen on unit price that fails step 2 costs far
more than it saved.

## Always record why

Every non-obvious part choice gets a line in the design documentation — which
alternatives were considered and what decided it. Use
`hw-documentation` and write an ADR when the decision constrains anything
downstream (a regulator that sets the thermal budget, a connector that sets the
enclosure opening).

Link the part choice back to the requirement that drove it with a `File`
relation, so `req_trace.py` can see it.

## What to hand back to the human

When you present a selection, give:

* the part number, and one sentence on why it wins
* the constraint that eliminated the runner-up
* stock and lead time as of now, with the date you checked
* anything that makes it risky: single source, long lead, new silicon, an
  end-of-life notice

If a requirement forces a part that is risky on availability, say so at
selection time — that is a requirements conversation, and it is much cheaper
now than after layout.
