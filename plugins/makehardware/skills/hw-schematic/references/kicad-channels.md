# Which channel touches a KiCad file, and what to do when one fails

Four things can read or write a `.kicad_*` file here, and they do not overlap.
Reaching for the wrong one is most of what "KiCad automation is flaky" turns
out to be, so this is the map.

**This changed in 0.7.0.** Konnect — an MCP server exposing 214 tools over
KiCad's IPC API — was replaced by [ki-stack](https://github.com/Milind220/ki-stack),
a set of skills that teach an agent to drive the substrates directly. If you
are reading guidance that says "all writes go through Konnect MCP tools", it is
stale: run `hw-repair kicad`, which installs ki-stack and deletes the leftover
Konnect skills and agents from the snapshot.

## The four channels

| | `kicad-python` (IPC) | `kicad-cli` | `kiutils-rs` / `kicad-skip` | `sch-lint` / `pcb-lint` |
|---|---|---|---|---|
| **Authors** — place, wire, route, edit | yes, live | **no** | yes, offline and structural | no |
| **Checks** — ERC, DRC | via the running app | yes | no | yes, plus house rules the CLI has no concept of |
| **Exports** — PDF, SVG, Gerber, BOM, 3D | no | yes | no | writes the findings overlay |
| **Reads** — nets, pins, positions, hierarchy | yes | only via an export | yes | yes |
| **Needs a running KiCad** | **yes** | no | no | no |

The ki-stack skills that own each: `ki-stack-live` (IPC), `ki-stack-render`
and `ki-stack-verify` (CLI), `ki-stack-file-surgery` (structural edits),
`ki-stack-orient` (choosing between them). Start at `ki-stack-orient` when the
route is not obvious — that is what it is for.

### `kicad-cli` still cannot author. That has not changed.

Its complete verb list on KiCad 10 is:

```
kicad-cli sch  { erc, export, upgrade }
kicad-cli pcb  { drc, export, import, render, upgrade }
kicad-cli sym  { export, upgrade }        kicad-cli fp { export, upgrade }
```

No `add`, no `place`, no `route`, no `connect`. KiCad ships no headless
authoring CLI and never has. So authoring is IPC or structured file edits —
there is no third option, and that is exactly why the plugin needs *something*
in this space rather than leaving the agent to invent one.

### The rule that changed, and the one that did not

**Changed:** structured, parser-backed edits to a `.kicad_*` file are now a
first-class route, not a last resort. `kiutils-rs` round-trips the file
losslessly, preserving formatting and tokens it does not understand, and
`ki-stack-file-surgery` is the skill for it. Schematic work in particular is
often better off here than through IPC, because the schematic editor's IPC
surface is thinner than the board's.

**Did not change:** never hand-roll an S-expression edit. `sed`, a regex, or a
string replace on a `.kicad_sch` invalidates UUIDs, symbol instance paths and
cross-sheet references — the file still opens, the netlist is wrong, and
nothing tells you until fabrication. Use a parser or use the IPC. The
distinction is *structural versus textual*, not *tool versus file*.

`scripts/kicad_sexpr.py` in this plugin is a **reader**. `sch-lint` and
`pcb-lint` go through it and only ever read. Do not write with it.

## Live IPC needs a running KiCad

`kicad-python` talks to an application, not a file, so a headless session has
nothing to connect to until you start one:

```bash
hw-kicad-up hw/board.kicad_pro     # Xvfb + KiCad, IPC at /tmp/kicad/api.sock
kicad-python-smoke connect         # prove the socket answers before scripting
```

Render, export, ERC, DRC and structured file edits all run headless and need
none of that. Only reach for the live path when the task genuinely is live
board automation — `ki-stack-live` says which those are.

## When a KiCad step fails

Work down this list. Most failures are one of the first three, and none of them
is a reason to stop the task.

1. **Orient before diagnosing.** `ki-stack-orient`'s preamble runs
   `kicad-project-find`, `kicad-version` and `kicad-python-smoke` in one go and
   usually names the problem: wrong file, wrong KiCad major, no IPC.

2. **`ipc_connect=failed`.** No KiCad running (`hw-kicad-up`), the API disabled
   in preferences, a busy KiCad, or a version mismatch. It is not a reason to
   fall back to text editing — take the file-surgery route instead.

3. **The pack is missing or the helpers are not found.** `hw-doctor` reports
   `ki-stack skills`; `hw-repair kicad` installs it. The skills locate their own
   helpers through `$KI_STACK_DIR`, so an unset `KI_STACK_DIR` makes them look
   under the *project* directory and find nothing.

4. **`kicad-cli` refuses the file.** Almost always a major-version mismatch —
   `kicad-cli sch upgrade` / `pcb upgrade`, and say in the review that the file
   format moved.

5. **Only now escalate**, with the command, its output and what you tried. A
   failure you worked around silently is worse than one you reported: the next
   session hits it again with none of what you learned.

## What to tell the human

`ki-stack`'s own rule is the house rule too: **no success claim without
evidence** — an artefact path, DRC/ERC output, a changed-file list, or script
output. A render-after-edit is the cheapest proof there is and `ki-stack-verify`
exists to make it routine. Put it on the review page rather than describing it.
