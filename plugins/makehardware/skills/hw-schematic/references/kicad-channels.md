# Which channel touches a KiCad file, and what to do when Konnect fails

Three things can read or write a `.kicad_*` file here, and they do not overlap.
Reaching for the wrong one is most of what "Konnect keeps failing" turns out to
be, so this is the map.

## The three channels

| | Konnect MCP | `kicad-cli` | `sch-lint` / `pcb-lint` |
|---|---|---|---|
| **Authors** — place, wire, route, edit | yes | **no** | no |
| **Checks** — ERC, DRC | yes (wraps the CLI) | yes | yes, plus house rules the CLI has no concept of |
| **Exports** — PDF, SVG, Gerber, BOM, 3D render | yes (wraps the CLI) | yes | writes the findings overlay |
| **Reads** — nets, pins, positions, hierarchy | yes | only via an export | yes |
| Needs a running server | yes | no | no |

### `kicad-cli` cannot author. That is the whole answer.

Its complete verb list on KiCad 10 is:

```
kicad-cli sch  { erc, export, upgrade }
kicad-cli pcb  { drc, export, import, render, upgrade }
kicad-cli sym  { export, upgrade }        kicad-cli fp { export, upgrade }
```

There is no `add`, no `place`, no `route`, no `connect`, no `set`. KiCad ships
no headless authoring CLI and never has — the editing API is the IPC API, which
is what Konnect speaks. So the question "should we use a direct CLI instead of
Konnect" has a factual answer: **there is no direct CLI to use instead.** The
alternatives to Konnect are the IPC API (which is what Konnect is), a
hand-written S-expression editor (see below), or the GUI, which no session has.

Konnect is therefore the right tool for authoring, and `kicad-cli` is the right
tool for exporting and checking — including when you call it yourself, which is
fine and is what `sch-lint`, `pcb-lint` and `review-artifact` all do. Nothing
requires an export to go through the MCP server.

### Editing the S-expressions by hand

`scripts/kicad_sexpr.py` parses and writes KiCad's format, and the lint tools
read every file through it. **It is a reader.** Writing a `.kicad_sch` with it
is a last resort, because the format carries UUIDs, symbol instance paths and
cross-sheet references that a text-level edit silently invalidates: the file
still opens, the netlist is wrong, and nothing tells you until fabrication.

If you genuinely have no other route, then: change one thing, re-run
`kicad-cli sch erc`, and say in the review request that the file was edited
outside the tool. Never do it as a shortcut around a Konnect call that is
merely inconvenient.

## When a Konnect call fails

Work down this list. Most failures are one of the first three and none of them
are a reason to stop the task.

1. **`hw-repair konnect`.** `konnect init` writes its two subagents with
   `tools: [mcp__konnect__*]`. Under this plugin the server namespaces to
   `mcp__plugin_makehardware_konnect__*`, so that glob matches nothing and both
   agents launch with **no tools at all** — and come back having "reviewed" a
   board they could not open. The repair rewrites the frontmatter; the session
   has to restart for it to take.

2. **The tool is not loaded.** Konnect exposes 214 tools across 20 toolsets and
   loads only `project` and `config` at startup. A tool you cannot see is
   almost never missing — it is in an unloaded toolset. `list_toolboxes` names
   them; `load_toolset("sch_wiring")` brings one in. Unload what you have
   finished with, or the context fills with tool definitions.

3. **The path is wrong.** Konnect takes absolute paths to a specific
   `.kicad_sch` or `.kicad_pcb`, not a project directory and not a relative
   path. `get_project_info` says what it thinks is open.

4. **The operation is refused, not broken.** Several tools refuse by design and
   name the working alternative in the error — `move_connected` is the common
   one, which refuses and points at `move_schematic_component`. Read the
   message; it is telling you what to call instead.

5. **`get_recent_calls` / `server_stats`.** Every call is logged to
   `~/.konnect/logs/calls.jsonl` with its arguments and its error. This is
   faster than re-deriving what went wrong, and it is the thing to quote if you
   are escalating.

6. **The transaction is stuck.** `konnect transaction status <project-dir>`,
   then `recover`. A killed session can leave one open, and every subsequent
   write on that project fails until it is cleared.

7. **Only now**: fall back to `kicad-cli` for anything that is an export or a
   check, do that part directly, and escalate the authoring step with the
   `calls.jsonl` line attached. Do not fall back to editing the file as text.

## What to tell the human

Escalate a Konnect failure only after the list above. When you do, give the
tool name, the arguments, and the logged error — not "Konnect failed". A
failure you worked around silently is worse than one you reported: the next
session hits it again with none of what you learned.
