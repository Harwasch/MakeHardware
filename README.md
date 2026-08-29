# MakeHardware

A Claude Code **plugin** that teaches AI agents to do hardware engineering, and
the cloud environment that gives them the tools to do it.

This repo is not a hardware project. It holds the workflow, practices, skills
and definitions; the projects themselves live in their own repos and install
this plugin.

```
MakeHardware  (this repo)          your-widget  (a project repo)
├── the workflow                   ├── plan.yaml
├── the skills                 ──► ├── requirements/
├── the house practices            ├── cad/  hw/  sim/
└── the environment setup          └── docs/{reference,design,user}
```

## Using it on a project

**Start here: [docs/03-using-it.md](docs/03-using-it.md)** walks through a whole
project from a one-sentence idea to a verified design.

The short version — in the project repo's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "makehardware": {
      "source": { "source": "github", "repo": "Harwasch/MakeHardware" }
    }
  },
  "enabledPlugins": { "makehardware@makehardware": true }
}
```

That is enough on a local machine you have trusted for plugins. **In a cloud
session it is not sufficient on its own** — a repo-declared marketplace is
ignored for an untrusted folder, and `enabledPlugins` never installs anything.
The environment's setup script therefore installs the plugin at user scope; see
[docs/01-environment.md](docs/01-environment.md#why-the-setup-script-installs-the-plugin).

Then point the project at a cloud environment built from [`env/`](env/) and run
`/hw-new-project` to scaffold it.

To stop copying that file into every new repo by hand, make a **GitHub template
repository** out of [`templates/github-repo/`](templates/github-repo) — see
[docs/04-template-repo.md](docs/04-template-repo.md).

## The workflow

```
1 VISION ─► 2 PLAN ─► 3 REQS ─► 4 ARCHITECTURE ─► 5 DESIGN ─► 6 SIMULATE ─► 7 VERIFY
 interview   chunks &  decompose  block diagram    schematic   ngspice       evidence
 + renders   deps      + validate  + power budget   + CAD       FEA           + gate
     ▲          ▲          ▲            ▲              ▲           │            │
     │          │          │            │              └───────────┘            │
     │          │          │            └──── a rail is short ──────┤            │
     │          │          └────────── numbers must move ───────────┤            │
     └──────────┴──────── the thing is not what they meant ─────────────────────┘
```

Stages 1–4 are agreements with a human. Stages 5–7 are a loop. Full detail in
[docs/02-workflow.md](docs/02-workflow.md).

**Every agreement is a recorded one.** The agent is normally working in a cloud
VM, so the human's only review surface is this repository on github.com. At each
milestone the agent commits an artefact that renders there — a vision document,
the plan's scope and Gantt, the requirements map, the block diagram, a schematic
PDF — asks the human directly with the link, and records what they said in
`docs/review/reviews.yaml`. `review-gate check --gate` fails while a milestone
is unanswered, or while an artefact has changed since it was signed off. A
chunk in `plan.yaml` cannot be marked `done` until its review is signed and its
declared outputs exist on disk.

The rule behind it: **an artefact the human has not seen is not a deliverable.**

## What the plugin provides

| | |
|---|---|
| **Skills** | `hw-vision`, `hw-planning`, `hw-requirements`, `hw-block-diagram`, `hw-review`, `hw-sourcing`, `hw-simulation`, `hw-verification`, `hw-documentation`, `hw-imagegen`, `hw-retro` |
| **Commands** | `/hw-new-project`, `/hw-status`, `/hw-review`, `/hw-retro` |
| **Tools on PATH** | `hw-doctor`, `plan-render`, `req-trace`, `block-diagram`, `vision-board`, `review-gate`, `imagegen` |
| **MCP servers** | `konnect` (KiCad), `spice` (ngspice/LTspice), `build123d` |
| **Practices** | House standards for sourcing, connectors and passives — edited over time to steer the agent |

## The toolchain

| Layer | Tool |
|---|---|
| Human review | `review-gate` — artefacts that render on GitHub, a link put to the human, a committed sign-off with a digest per artefact |
| Requirements | StrictDoc, with a hardware grammar and a traceability gate, plus a draw.io/SVG requirements map |
| Architecture | `block-diagram` — one YAML spec renders an editable draw.io file, a review SVG, and a power budget with a gate |
| Planning | `plan-render` — a dependency Gantt, an editable draw.io graph, and a scope document, with `done` checked against the filesystem |
| Schematic / PCB | KiCad 10 + Konnect (214 MCP tools), `kicad-cli` |
| Circuit simulation | ngspice via `ltspice-mcp`; LTspice opt-in |
| 3D CAD | build123d + `build123d-mcp` |
| Meshing / FEA | gmsh + CalculiX |
| Vision imagery | build123d renders for geometry; HF Spaces or a keyed API for styling |
| Design review | [kicad-happy](https://github.com/aklofas/kicad-happy) — EMC, thermal, derating, distributor search |

Why each, and what was rejected: [docs/00-stack.md](docs/00-stack.md).

## Setting up the environment

Three fields in the cloud environment dialog at
[claude.ai/code](https://claude.ai/code):

1. **Network access → Full.** Nothing to paste. Sourcing and documentation
   mean fetching datasheets from vendors you can't enumerate in advance, so an
   allowlist makes every new manufacturer a config change.
   [`env/allowed-domains.txt`](env/allowed-domains.txt) has the tighter
   Custom fallback if you'd rather not run open — note that on **Trusted** you
   silently get KiCad 7 instead of 10.
2. **Environment variables** ← [`env/environment-variables.env`](env/environment-variables.env)
3. **Setup script** ← [`env/setup.sh`](env/setup.sh) — this also installs the
   plugin itself, which is why a cloud session gets the skills and MCP servers
   without a trust dialog.

Then run `hw-doctor` in a session. Details and the five failure modes the
script works around: [docs/01-environment.md](docs/01-environment.md).

## Layout

```
.claude-plugin/marketplace.json   marketplace manifest
plugins/makehardware/
├── skills/                       the workflow stages
├── commands/                     /hw-new-project, /hw-status, /hw-review, /hw-retro
├── bin/                          hw-doctor, plan-render, req-trace, block-diagram,
│                                 vision-board, review-gate, imagegen
├── scripts/                      their implementations
├── templates/project/            what /hw-new-project scaffolds
└── .mcp.json                     konnect, spice, build123d
templates/github-repo/            contents of the GitHub template repository
env/                              cloud environment configuration
docs/                             stack rationale, environment, workflow
```

## Docs

* [docs/00-stack.md](docs/00-stack.md) — choices, rejections, measured build budget
* [docs/01-environment.md](docs/01-environment.md) — environment configuration
* [docs/02-workflow.md](docs/02-workflow.md) — the seven stages and their exit conditions
* [docs/03-using-it.md](docs/03-using-it.md) — how you actually run a project with it
* [docs/04-template-repo.md](docs/04-template-repo.md) — a GitHub template repo so new projects start correct
