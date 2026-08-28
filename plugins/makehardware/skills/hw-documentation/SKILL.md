---
name: hw-documentation
description: Manage the three kinds of hardware documentation - external reference material (datasheets, app notes, standards), internal design documentation (how and why we built it), and user documentation (manuals, spec sheets). Use when fetching a datasheet, recording a design decision, writing an ADR, or producing a manual.
---

# Documentation

Three kinds, with different owners, lifetimes and failure modes. Keeping them
apart is most of the discipline.

```
docs/
├── reference/    external — what other people published    (fetched, never edited)
├── design/       internal — how and why WE built it        (written as we go)
└── user/         outbound — how to use the thing           (written near the end)
```

## 1. Reference — external material

Datasheets, application notes, standards, errata, reference designs. **Never
edit these.** They are evidence, and an edited datasheet is worse than none.

Every file is recorded in `docs/reference/manifest.yaml`:

```yaml
- id: mcp1700-datasheet
  title: MCP1700 Low Quiescent Current LDO
  part: MCP1700T-3302E/TT
  publisher: Microchip
  revision: DS20001826D
  url: https://ww1.microchip.com/downloads/en/DeviceDoc/20001826D.pdf
  local: docs/reference/mcp1700-DS20001826D.pdf
  retrieved: 2026-08-28
  sha256: ...
  needed_by: [ELE-001]
```

Record `revision` and `retrieved`, always. A datasheet that silently revised
under you is a real failure mode, and the revision is how you notice.

**When you cannot fetch it.** Vendor sites are often outside the environment's
network allowlist, and some material is behind a login or an NDA. Do not guess
at a number from memory and do not silently proceed. Add the entry with
`local: null` and `blocked: <reason>`, then **ask the human to fetch it**, with
the exact URL and what you need from it. A parameter taken from memory instead
of a datasheet is exactly the confident wrong answer that gets a board
fabricated wrong.

Cite what you use: when a number comes from a datasheet, put the reference `id`
and the page or table in the requirement's `RATIONALE` or the ADR.

## 2. Design — how and why we built it

The documentation that makes the design maintainable by someone who was not
there. Written **as the work happens**, not reconstructed at the end.

Decisions that constrain anything downstream get an ADR in
`docs/design/adr-NNNN-<slug>.md`:

```markdown
# ADR-0002: Linear regulator for the always-on rail

## Status
Accepted — 2026-08-28

## Context
ELE-001 caps standby draw at 40 uA. The always-on rail is 3.3 V at under 5 mA.

## Decision
MCP1700 LDO rather than a switcher.

## Consequences
- Quiescent current 1.6 uA typ, which fits the 40 uA budget with margin.
- Dropout sets the minimum usable cell voltage at 3.5 V, which feeds SYS-001.
- Efficiency is poor above 5 mA; if the active rail ever moves here, revisit.

## Alternatives considered
- TPS62740 buck: better efficiency, 360 nA Iq, but 4x the cost and needs an
  inductor the enclosure has no room for at the current envelope (MEC-001).
```

Write the **Consequences** honestly, including the bad ones. That section is
what a future session reads when the number has to move.

Also in `docs/design/`: the architecture overview, interface definitions
(board outline, connector pinouts, mounting), and the verification report.

## 3. User — how to use the thing

Manuals, quick-start guides, the spec sheet for *our* product, safety and
regulatory statements. Written late, but **stub it early**: a product whose
specification sheet cannot be filled in is usually a product with a
requirements gap.

Pull the numbers from the requirements tree, not from memory — the spec sheet
and `requirements/` must not disagree. If they do, one of them is wrong and it
is worth finding out which before it ships.

## The rule that matters

**A number in any document traces to a source.** A datasheet reference, a
requirement UID, or a simulation result. A number with no source is a guess
wearing a document's clothes, and it will be believed.
