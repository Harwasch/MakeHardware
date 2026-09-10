# Which channel touches a KiCad file, where KiStack fits, and who wins

Four things can read or write a `.kicad_*` file here, and they do not overlap.
Reaching for the wrong one is most of what "KiCad automation is flaky" turns
out to be, so this is the map — followed by the part that actually costs time,
which is what to do where KiStack's house practice and this toolbox's disagree.

**Two packs preceded this one.** Konnect (an MCP server, 214 tools) through
0.6.0; ki-stack through 0.7.0. If you are reading guidance that says "all
writes go through Konnect MCP tools", or that names a `ki-stack-*` skill, it is
stale — run `hw-repair kicad`, which installs
[KiStack](https://github.com/American-Embedded/KiStack) and clears the old pack
out of the snapshot.

## The four channels

| | `kicad-cli` | `kicad-python` (IPC) | direct file edit | `sch-lint` / `pcb-lint` |
|---|---|---|---|---|
| **Authors** | **no** | yes, live | yes, and this is what KiStack assumes | no |
| **Checks** — ERC, DRC | yes | via the running app | no | yes, plus house rules the CLI has no concept of |
| **Exports** — PDF, SVG, Gerber, BOM, 3D | yes | no | no | writes the findings overlay |
| **Needs a running KiCad** | no | **yes** | no | no |

`kicad-cli` has no `add`, `place`, `route` or `connect` verb on KiCad 10 and
never has, so authoring is IPC or the file itself. KiStack's own rule:
**prefer the IPC bindings wherever they are available** — `hw-kicad-up` starts
a KiCad and `kipy` connects to it. Fall back to editing the file when there is
no session to talk to.

When you do edit a file: change one thing, re-export, and look at it. Never
`sed` a `.kicad_sch` — a text-level edit invalidates UUIDs, symbol instance
paths and cross-sheet references, the file still opens, and the netlist is
quietly wrong. `scripts/kicad_sexpr.py` here is a **reader**; `sch-lint` and
`pcb-lint` go through it and only ever read.

## The KiStack skills

`kicad-schematic`, `kicad-pcb`, `kicad-layout`, `kicad-symbol`,
`kicad-footprint`, `kicad-bom`, `kicad-export`, `kicad-gerbers`,
`kicad-panelize`, `pcb-product-render`. `kicad-export` carries a reference page
for every `kicad-cli` verb, which is the fastest way to get an export flag
right.

They are human-written house practice from a working shop, and the best thing
in them is the insistence on **iterating on rendered images**: plot the sheet
to SVG, look at it, fix what is ugly, look again. That is the same instinct as
`review-artifact` and `hw-optimize`, applied at a finer grain, and it is worth
following.

## Where KiStack and this toolbox disagree — and who wins

**The gate wins.** `sch-lint`, `pcb-lint` and `review-gate` are the things that
actually fail a stage, and a design that satisfies advice while failing a gate
is not shippable. KiStack supplies craft where the gates are silent.

Three specific collisions, so nobody has to discover them at review time:

| | KiStack says | This toolbox says | Take |
|---|---|---|---|
| **Sheet strategy** | prefer a single sheet you can see at once, bigger paper if needed | a sheet plan derived from the agreed block diagram, A3 default, one sheet per functional group | **the sheet plan.** `sch-lint --plan` binds every sheet back to the architecture a human signed off, and its density check fails an overfull sheet. A single huge sheet also does not render on the review page. |
| **Changing the schematic during layout** | feel free, do pin swaps to clean up routing | the schematic is an agreed artefact | **do it, then re-open the review.** The advice is right — pin swaps are how a board gets routable. But `review-gate` marks the schematic review stale the moment its artefact changes, and that is correct: the human agreed to a different drawing. Say what moved and why. |
| **Autorouting** | avoid it; route manually unless the board is very dense | `hw-verification/references/pcb-layout.md` documents freerouting | **no conflict.** Both say manual first. The freerouting notes exist for the dense case KiStack also allows. |

One that people expect to collide and does not: KiStack's **50 mil label text**
is exactly the house `text_size_mm: 1.27` in `templates/kicad/house-defaults.json`,
which is what `SCH-TEXTSIZE` checks. They agree.

## When a KiCad step fails

1. **Check the obvious first.** `kicad-cli version` (must be 10.x — a KiCad 7
   from Ubuntu universe has no IPC API at all), and that the path you are
   passing is the project's canonical file.
2. **`kipy` cannot connect.** No KiCad running (`hw-kicad-up`), the API server
   disabled in preferences, a busy KiCad, or a version mismatch. Not a reason
   to reach for a text editor — work on the file with a parser, or export and
   check what you have.
3. **The pack is missing.** `hw-doctor` reports `kistack`; `hw-repair kicad`
   installs it and clears any previous pack.
4. **`kicad-cli` refuses the file.** Almost always a major-version mismatch —
   `kicad-cli sch upgrade` / `pcb upgrade`, and say in the review that the file
   format moved.
5. **Only now escalate**, with the command, its output, and what you tried. A
   failure you worked around silently is worse than one you reported: the next
   session hits it again with none of what you learned.

## What to tell the human

**No success claim without evidence** — an artefact path, ERC/DRC output, a
changed-file list, or a render. A plot-after-edit is the cheapest proof there
is. Put it on the review page rather than describing it.
