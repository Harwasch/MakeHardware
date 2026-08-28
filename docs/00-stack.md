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
| Design review | **kicad-happy** (MIT) | Read-only analysers Konnect does not have: EMC pre-compliance, thermal, voltage derating, datasheet cross-reference, distributor search. Pure Python, needs no KiCad install. |
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

Worth knowing that the loud failure was itself wrong for a while. The check
was `apt-cache policy kicad | grep -q "kicad-10.0-releases"`, and under
`set -o pipefail` a *matching* grep exits first, `apt-cache` takes SIGPIPE, and
the pipeline reports 141. So the phase announced "PPA unreachable" on builds
where the PPA was reachable, the index fetched and the candidate correctly
pinned at 10.0.5 — and KiCad never got installed. The check now captures the
output and matches it with `case`. See `docs/01-environment.md`.

### Konnect is downloaded, not built — the proxy does serve release assets

This repo used to build Konnect from source on the belief that the session's
GitHub proxy 403s release assets. That belief came from probing the wrong two
URLs. The proxy scopes the **API** and the release **web pages** to attached
repositories; the asset path itself is served:

```
https://api.github.com/repos/mixelpixx/Konnect/releases  -> 403
https://github.com/mixelpixx/Konnect/releases/latest     -> 403
https://github.com/mixelpixx/Konnect/releases/download/v0.10.0/\
  konnect-v0.10.0-x86_64-unknown-linux-gnu.tar.gz        -> 200
```

So `gh release download` and anything API-driven genuinely does fail here —
that part of the original finding holds, and it is why the mistake was easy to
make. A plain `curl` of the asset does not fail. Verified on the image: 11 MB,
seconds to fetch, `konnect 0.10.0` runs, three dynamic dependencies, and its
highest symbol requirement is `GLIBC_2.39` — exactly what Ubuntu 24.04 ships.

The skills and agents are embedded in the binary, not read from the checkout:
`konnect init --client claude` installs all six skills and both agents from the
downloaded binary alone. So the clone is not needed for those either.

That removes ~4 minutes from the build — the phase that used to overrun the
budget and get the whole script killed — along with `cmake`, `pkg-config`,
`protobuf-compiler`, `libprotobuf-dev` and a multi-GB cargo tree.

Upstream publishes no checksums file, so `env/setup.sh` pins its own SHA-256 of
the asset next to the version and treats a mismatch as a hard failure. Bump the
two together. `MH_KONNECT_FROM_SOURCE=1` restores the source build, kept
working as the fallback if upstream ever stops shipping a Linux asset.

Note that *downloading* upstream's own asset carries none of the AGPL
source-offer obligation that re-hosting a mirrored binary on our own repo
would have. Not mirroring remains the right call, for a better reason.

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

### Konnect and kicad-happy are complementary, not competing

Both provide KiCad skills, and their triggers overlap. They do different jobs:
Konnect *changes* designs through KiCad 10's IPC API and a native S-expression
engine, and its own rules make routing edits through it mandatory because
direct file edits corrupt `.kicad_*` files. kicad-happy *reads* designs — pure
Python analysers producing structured reports, plus distributor search and
datasheet extraction.

So the rule is: writes go through Konnect, reads go through kicad-happy, and
the decision about which part to actually buy stays in `hw-sourcing` where the
house standards live. The full precedence table ships in the project
`CLAUDE.md`.

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
| Building Konnect from source | Was the default until the 403 finding was retested. ~4 min for something `curl` does in seconds. Still available behind `MH_KONNECT_FROM_SOURCE=1`. |
| Mirroring Konnect on our own repo | Would work — the proxy serves attached repos — but re-hosting the binary carries an AGPL source-offer obligation, and the upstream asset is directly fetchable anyway. |
| LTspice as the default | Blocked domain, ~2 GB, and unnecessary — ngspice covers the loop. |
| `pip` for the Python stack | `uv` does the same install in **10 s** vs. minutes. |
| Doorstop, sphinx-needs | Weaker typed grammars and no ReqIF path out. |
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
| Konnect release download + install | **~5 s** (was 78 s warm / ~3.5 min cold from source) |
| KiCad 10 from PPA | dominated by download |
| **Total (parallel)** | **~2 min** |

LTspice, when enabled, adds roughly 2 GB and pushes this past the budget —
another reason it is opt-in.

The budget is not a soft target: overrunning it kills the script mid-phase.
That happened on a cold build where the Konnect compile was still running at
the limit, and because the script's tail wrote `status.json` and the helper
commands *after* everything else, the session came up with no toolchain and no
diagnosis. The script now writes helpers first, rewrites `status.json` after
every phase, and runs its tail from an `EXIT`/`TERM` trap, so a build that is
cut short still explains itself to `hw-doctor`.
