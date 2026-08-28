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

In the project repo's `.claude/settings.json`:

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

Then point the project at a cloud environment built from [`env/`](env/) and run
`/hw-new-project` to scaffold it.

## The workflow

```
1 VISION ─► 2 PLAN ─► 3 REQUIREMENTS ─► 4 DESIGN ─► 5 SIMULATE ─► 6 VERIFY
 interview   chunks &   decompose &      schematic   ngspice        evidence
 + renders   deps       validate         + CAD       FEA            + gate
     ▲          ▲            ▲               ▲           │             │
     │          │            │               └───────────┘             │
     │          │            └────── numbers must move ────────────────┤
     └──────────┴───── the thing is not what they meant ───────────────┘
```

Stages 1–3 are agreements with a human. Stages 4–6 are a loop. Full detail in
[docs/02-workflow.md](docs/02-workflow.md).

## What the plugin provides

| | |
|---|---|
| **Skills** | `hw-vision`, `hw-planning`, `hw-requirements`, `hw-sourcing`, `hw-simulation`, `hw-verification`, `hw-documentation` |
| **Commands** | `/hw-new-project`, `/hw-status` |
| **Tools on PATH** | `hw-doctor`, `plan-render`, `req-trace`, `vision-board` |
| **MCP servers** | `konnect` (KiCad), `spice` (ngspice/LTspice), `build123d` |
| **Practices** | House standards for sourcing, connectors and passives — edited over time to steer the agent |

## The toolchain

| Layer | Tool |
|---|---|
| Requirements | StrictDoc, with a hardware grammar and a traceability gate |
| Schematic / PCB | KiCad 10 + Konnect (214 MCP tools), `kicad-cli` |
| Circuit simulation | ngspice via `ltspice-mcp`; LTspice opt-in |
| 3D CAD | build123d + `build123d-mcp` |
| Meshing / FEA | gmsh + CalculiX |
| Vision imagery | build123d renders for geometry, Hugging Face Spaces for styling |

Why each, and what was rejected: [docs/00-stack.md](docs/00-stack.md).

## Setting up the environment

Three fields in the cloud environment dialog at
[claude.ai/code](https://claude.ai/code):

1. **Network access → Custom**, tick *"Also include default list of common
   package managers"*, add [`env/allowed-domains.txt`](env/allowed-domains.txt).
   Without `ppa.launchpadcontent.net` you silently get KiCad 7 instead of 10.
2. **Environment variables** ← [`env/environment-variables.env`](env/environment-variables.env)
3. **Setup script** ← [`env/setup.sh`](env/setup.sh)

Then run `hw-doctor` in a session. Details and the five failure modes the
script works around: [docs/01-environment.md](docs/01-environment.md).

## Layout

```
.claude-plugin/marketplace.json   marketplace manifest
plugins/makehardware/
├── skills/                       the workflow stages
├── commands/                     /hw-new-project, /hw-status
├── bin/                          hw-doctor, plan-render, req-trace, vision-board
├── scripts/                      their implementations
├── templates/project/            what /hw-new-project scaffolds
└── .mcp.json                     konnect, spice, build123d
env/                              cloud environment configuration
docs/                             stack rationale, environment, workflow
```

## Docs

* [docs/00-stack.md](docs/00-stack.md) — choices, rejections, measured build budget
* [docs/01-environment.md](docs/01-environment.md) — environment configuration
* [docs/02-workflow.md](docs/02-workflow.md) — the six stages and their exit conditions
