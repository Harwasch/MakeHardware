# The stack, and why

Every choice below was run in a real Claude Code cloud VM (Ubuntu 24.04,
4 vCPU / 16 GB / 30 GB) before it was written down. Timings are measured, not
estimated.

## What we run

| Layer | Tool | Why this one |
|---|---|---|
| Planning | **plan.yaml** + `plan-render` | Session-sized chunks with explicit dependencies, scheduled by longest path, rendered as a dependency Gantt into the README. |
| Requirements | **StrictDoc** 0.28.3 | Plain-text `.sdoc` in git, typed grammar, parent/child relations, refuses to build a tree with a dangling parent or duplicate UID. Exports HTML, JSON and ReqIF. |
| Schematic / PCB | **KiCad 10** + **Konnect** 0.10.0 | Konnect is a single Rust binary exposing 214 MCP tools over KiCad 10's IPC API, with a native S-expression engine for file-based schematic work. |
| PCB checks & output | **kicad-cli** | ERC, DRC, netlist, gerbers, STEP. Headless, scriptable, no GUI needed. |
| Circuit simulation | **ngspice 42** via **ltspice-mcp** 0.5.0 | Headless, no Wine, first-class backend in the MCP server. Returns parsed measurements, not plots. |
| Circuit simulation (opt-in) | **LTspice** under Wine | Only for vendor-encrypted ADI models and `.asc` editing. Off by default. |
| 3D CAD | **build123d** 0.11.1 + **build123d-mcp** | Parametric Python CAD on OCCT. Models are code, so they diff, review and re-render on a changed number. |
| Meshing / FEA | **gmsh** 4.12.1 + **CalculiX** 2.21 | Both in the Ubuntu archive, both headless. Thermal and structural. |
| Vision renders | **matplotlib** + build123d tessellation | Shaded views and isometric line art from real geometry. |
| Vision styling | **Hugging Face Spaces** (FLUX Kontext, Qwen) | Restyles a geometry render without inventing new proportions. No API key needed. |

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

Downloading the prebuilt `konnect-pcm-v0.10.0-linux.zip` would be faster, and
it does not work here. The session's GitHub proxy scopes API and release-asset
requests to repositories attached to the session, and Konnect is not one of
them. Both paths return 403:

```
https://github.com/mixelpixx/Konnect/releases/latest      -> 403
https://api.github.com/repos/mixelpixx/Konnect/releases/latest -> 403
  {"message":"GitHub access to this repository is not enabled for this session..."}
```

Attaching the repo does not help either: the setup script runs during the
environment build, before any session exists, so there is nothing to attach it
to. A plain `git clone` of the public repo *is* served, and `crates.io` is
reachable directly, so source is the only path that works unattended.

It is also not the bottleneck. Measured **78 s** warm, ~3.5 min cold, and it
only runs when the environment cache rebuilds — on a setup-script change, an
allowlist change, or roughly weekly.

The alternative, if the build ever does become a problem: mirror the binary as
a release asset on *your own* repo, which the proxy will serve. That is
permitted by the AGPL but carries a source-offer obligation, and it needs
re-mirroring on every Konnect release. Not worth it at 78 seconds.

### Image generation comes from the Hugging Face connector

The vision stage wants real imagery for styling, and there is no image model in
the environment itself. The connector already attached to this account exposes
FLUX, Qwen and — the important one — `FLUX.1-Kontext-Dev`, which *edits* an
input image. Seeding it with a build123d render keeps the proportions honest
while restyling material and finish, which a pure text-to-image model cannot
do.

It needs no API key and no allowlist entry. The one catch is a `gradio=none`
header on the connector that disables `invoke`; see
`docs/01-environment.md`. A paid direct API remains the upgrade path when
shared-GPU latency stops being acceptable.

### Konnect needs a running KiCad only for part of its job

Its own requirements are explicit: "For most PCB tools: KiCAD running with the
target board open (IPC API)". But schematic work goes through a native
S-expression engine, `place_component`/`move_component`/`rotate_component`
fall back to a closed board file, and ERC/DRC/exports go through `kicad-cli`.

So the agent works headless by default and escalates to a live GUI
(`hw-kicad-up`) only for live board editing. This matters because the
environment snapshot preserves **files, not processes** — a KiCad started
during setup is gone by the time a session runs.

### This repo is a plugin, not a project

The workflow has to apply to many hardware projects that live in their own
repos, and it has to improve over time without every project being re-scaffolded.
That is what the Claude Code plugin system is for: skills, commands, agents,
hooks, MCP servers and `bin/` executables ship as one versioned unit, and a
project repo opts in with four lines in `.claude/settings.json`.

The alternative — a template repo that projects copy — was rejected because
copies diverge. A house practice learned on project three would never reach
projects one and two. With a marketplace, editing `hw-sourcing/references/`
here updates every project on the next session.

Per-project files (`plan.yaml`, `requirements/`, `docs/`) live in
`templates/project/` and are scaffolded once by `/hw-new-project`. They are
starting structure, not shared code, so divergence there is correct.

## What we rejected

| Rejected | Why |
|---|---|
| `add-apt-repository` | Depends on `apt_pkg`, which this image's Python 3.11 default cannot import. See `docs/01-environment.md`. |
| KiCad from Ubuntu universe | 7.0.11, no IPC API. |
| Konnect release binaries | GitHub proxy 403s assets from unattached repos. |
| LTspice as the default | Blocked domain, ~2 GB, and unnecessary — ngspice covers the loop. |
| `pip` for the Python stack | `uv` does the same install in **10 s** vs. minutes. That headroom is what pays for the Konnect build. |
| Doorstop, sphinx-needs | Weaker typed grammars and no ReqIF path out. |
| Konnect release binaries (again, on merit) | Faster, but 403 from an unattached repo, and mirroring them ourselves carries an AGPL source-offer obligation for 78 seconds of build time. |
| A template repo instead of a plugin | Copies diverge; a practice learned on one project never reaches the others. |
| A paid image API as the default | The Hugging Face connector already does it with no key and no allowlist change. Kept as a documented upgrade path. |
| Geometry renders *alone* for vision | They fix proportion but say nothing about material or finish, which is most of what a human reacts to. Geometry sets the numbers; generation does the styling. |

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
