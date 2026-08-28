# The stack, and why

Every choice below was run in a real Claude Code cloud VM (Ubuntu 24.04,
4 vCPU / 16 GB / 30 GB) before it was written down. Timings are measured, not
estimated.

## What we run

| Layer | Tool | Why this one |
|---|---|---|
| Requirements | **StrictDoc** 0.28.3 | Plain-text `.sdoc` in git, typed grammar, parent/child relations, refuses to build a tree with a dangling parent or duplicate UID. Exports HTML, JSON and ReqIF. |
| Schematic / PCB | **KiCad 10** + **Konnect** 0.10.0 | Konnect is a single Rust binary exposing 214 MCP tools over KiCad 10's IPC API, with a native S-expression engine for file-based schematic work. |
| PCB checks & output | **kicad-cli** | ERC, DRC, netlist, gerbers, STEP. Headless, scriptable, no GUI needed. |
| Circuit simulation | **ngspice 42** via **ltspice-mcp** 0.5.0 | Headless, no Wine, first-class backend in the MCP server. Returns parsed measurements, not plots. |
| Circuit simulation (opt-in) | **LTspice** under Wine | Only for vendor-encrypted ADI models and `.asc` editing. Off by default. |
| 3D CAD | **build123d** 0.11.1 + **build123d-mcp** | Parametric Python CAD on OCCT. Models are code, so they diff, review and re-render on a changed number. |
| Meshing / FEA | **gmsh** 4.12.1 + **CalculiX** 2.21 | Both in the Ubuntu archive, both headless. Thermal and structural. |
| Vision renders | **matplotlib** + build123d tessellation | Shaded views and isometric line art from real geometry. |

## The decisions worth arguing about

### ngspice is the default simulator, not LTspice

The original draft made LTspice authoritative. Three things argue against it:

1. `ltspice.analog.com` is **not** in the Trusted network allowlist, so the
   MSI download fails and takes the setup script down with it.
2. Wine plus the MSI is roughly 2 GB and several minutes of the ~5 minute
   environment-build budget.
3. `ltspice-mcp` treats ngspice as a first-class backend — "simulate, parse,
   diagnose, analyze… open-source path with no LTspice install".

ngspice runs headless, starts instantly and needs no allowlist change. An RC
low-pass measured `fc = 997.7 Hz` against 1 kHz theoretical on the first run.

LTspice is still worth having when you need vendor-encrypted ADI models or
`.asc` schematic editing — set `MH_ENABLE_LTSPICE=1` and add `*.analog.com`
to the allowlist. It is a supplement, not the foundation.

### KiCad 10 must come from the PPA, and that needs an allowlist entry

Ubuntu 24.04 universe carries **KiCad 7.0.11**, which has no IPC API. Konnect
cannot drive it. KiCad 10.0.5 is published for noble on the KiCad PPA.

The trap: PPA content is served from `ppa.launchpadcontent.net`, and the
Trusted allowlist names only `launchpad.net` and the **retired**
`ppa.launchpad.net` (which now fails to connect at all). So without a Custom
allowlist entry, `apt-get update` prints a warning, **still exits 0**, and
`apt-get install kicad` quietly installs KiCad 7 from universe. The failure is
silent and lands three steps later as "Konnect can't connect".

`env/setup.sh` pins the PPA with an apt preference and then explicitly asserts
the installed major version, so this fails loudly instead.

### Konnect is built from source, not downloaded

The GitHub proxy scopes release-asset downloads to repositories attached to the
session, so `github.com/mixelpixx/Konnect/releases/...` returns 403. A plain
`git clone` of the public repo works fine, and `crates.io` is reachable
directly. Measured build: **78 s** warm, ~3.5 min cold.

### Konnect needs a running KiCad only for part of its job

Its own requirements are explicit: "For most PCB tools: KiCAD running with the
target board open (IPC API)". But schematic work goes through a native
S-expression engine, `place_component`/`move_component`/`rotate_component`
fall back to a closed board file, and ERC/DRC/exports go through `kicad-cli`.

So the agent works headless by default and escalates to a live GUI
(`hw-kicad-up`) only for live board editing. This matters because the
environment snapshot preserves **files, not processes** — a KiCad started
during setup is gone by the time a session runs.

## What we rejected

| Rejected | Why |
|---|---|
| `add-apt-repository` | Depends on `apt_pkg`, which this image's Python 3.11 default cannot import. See `docs/01-environment.md`. |
| KiCad from Ubuntu universe | 7.0.11, no IPC API. |
| Konnect release binaries | GitHub proxy 403s assets from unattached repos. |
| LTspice as the default | Blocked domain, ~2 GB, and unnecessary — ngspice covers the loop. |
| `pip` for the Python stack | `uv` does the same install in **10 s** vs. minutes. That headroom is what pays for the Konnect build. |
| Doorstop, sphinx-needs | Weaker typed grammars and no ReqIF path out. |
| An image model for vision boards | Not available in this environment, and geometry-based renders are better here anyway: they cannot depict something unbuildable, and every picture carries a bounding box and a volume. |

## Measured build budget

Setup scripts should finish in about five minutes so the filesystem snapshot
can cache. Phases run concurrently, so the wall clock is roughly the longest
one, not the sum.

| Phase | Measured |
|---|---|
| Base apt packages | 22 s |
| Python stack via uv (1.6 GB) | 10 s |
| Konnect clone + cargo build | 78 s warm / ~3.5 min cold |
| KiCad 10 from PPA | dominated by download |
| **Total (parallel)** | **~4 min** |

LTspice, when enabled, adds roughly 2 GB and pushes this past the budget —
another reason it is opt-in.
