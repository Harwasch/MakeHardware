# MakeHardware

AI-driven hardware engineering: a cloud environment, a set of skills and a
requirements system that let an agent take a product from a sentence to a
verified design.

The agent interviews you about what you actually want, shows you renders you
can judge by eye, decomposes the agreed vision into traceable requirements,
then runs a design → simulate → verify loop against them.

## Quick start

1. Create a cloud environment at [claude.ai/code](https://claude.ai/code).
2. **Network access → Custom**, tick *"Also include default list of common
   package managers"*, and add the lines from
   [`env/allowed-domains.txt`](env/allowed-domains.txt).
   Without `ppa.launchpadcontent.net` you silently get KiCad 7 instead of 10 —
   see [docs/01-environment.md](docs/01-environment.md).
3. Paste [`env/environment-variables.env`](env/environment-variables.env) into
   **Environment variables**.
4. Paste [`env/setup.sh`](env/setup.sh) into **Setup script**.
5. Start a session and run `scripts/hw-doctor.sh`.

## What's in the box

| | |
|---|---|
| **Electrical** | KiCad 10 + Konnect (214 MCP tools), `kicad-cli`, ngspice via `ltspice-mcp`, LTspice optional |
| **Mechanical** | build123d + `build123d-mcp`, gmsh, CalculiX |
| **Requirements** | StrictDoc with a hardware grammar, plus a traceability gate |
| **Vision** | Geometry-based concept renders you can react to |

## The workflow

```
1 VISION ──► 2 REQUIREMENTS ──► 3 DESIGN ──► 4 SIMULATE ──► 5 VERIFY
 interview     decompose &        schematic    ngspice        evidence
 + renders     validate           + CAD        FEA            + gate
      ▲              ▲                ▲            │              │
      │              │                └────────────┘              │
      │              └────── numbers must move ───────────────────┤
      └──────── the thing is not what they meant ─────────────────┘
```

Full detail in [docs/02-workflow.md](docs/02-workflow.md).

## Layout

```
concepts/         build123d concept modules for the vision stage
requirements/     StrictDoc .sdoc tree + shared grammar
cad/              build123d design models
sim/              SPICE decks and simulation results
env/              cloud environment configuration
scripts/          hw-doctor, vision_board, req_trace, session-start
.claude/skills/   hw-vision, hw-requirements, hw-simulation, hw-verification
docs/             stack rationale, environment setup, workflow
```

## Common commands

```bash
scripts/hw-doctor.sh                                  # what works right now

/opt/hw-py/bin/python scripts/vision_board.py \
    concepts/concept_a.py concepts/concept_b.py --out build/vision

/opt/hw-py/bin/strictdoc export requirements \
    --output-dir build/requirements --formats=html,json
/opt/hw-py/bin/python scripts/req_trace.py --gate     # exit 1 on gaps

hw-display-start                                      # Xvfb :99
hw-kicad-up project.kicad_pro                         # live KiCad for Konnect IPC
```

## Docs

* [docs/00-stack.md](docs/00-stack.md) — what we chose, what we rejected, and
  the measured build budget
* [docs/01-environment.md](docs/01-environment.md) — environment configuration,
  and the five failure modes in the original setup script
* [docs/02-workflow.md](docs/02-workflow.md) — the five stages and their exit
  conditions
