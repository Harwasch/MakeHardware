# <project name>

A hardware project built with the [MakeHardware](https://github.com/Harwasch/MakeHardware)
workflow. Replace this paragraph with one sentence about what the thing is.

<!-- PLAN:BEGIN -->
<!-- PLAN:END -->

## Getting started

This repo was created from the MakeHardware project template, so
`.claude/settings.json` is already correct. In the **first** session, run:

```
/hw-new-project
```

That scaffolds `plan.yaml`, `requirements/`, `hw/`, `cad/`, `concepts/`,
`sim/`, `docs/`, `strictdoc.toml` and a project `CLAUDE.md` from the plugin's
current templates, then runs `hw-doctor` and `imagegen --list` so you know what
the toolchain can actually do before you plan around it.

Then start the vision interview:

```
Use hw-vision. I want to build <one sentence>.
```

## The commands you will use

```bash
hw-doctor                 # what the toolchain can actually do right now
/hw-status                # progress, what is ready to start, what is waiting on you
/hw-review <milestone>    # build the artefact, ask you about it, record the answer
plan-render               # refresh docs/plan.{svg,md,drawio} and the block above
plan-render --check       # exit 1 on a `done` chunk whose outputs or review are missing
block-diagram             # refresh the architecture diagram and power budget
block-diagram --check     # architecture gate; exit 1 on an over-budget rail
req-trace --gate          # traceability gate; exit 1 while gaps remain
req-trace --map           # redraw the requirements map
review-gate list          # where every human review stands
```

## How you get asked things

Claude runs in a cloud VM, so it cannot show you anything directly. At each
milestone — the vision, the plan, the requirements, the architecture, and each
large design stage — it commits something that renders here on GitHub and then
asks you, with the link:

| Look at | For |
|---|---|
| `docs/design/vision.md` | the concepts, their envelopes and masses |
| `docs/plan.md` | what each chunk of work actually is |
| `docs/design/requirements-map.svg` | the requirement tree and its gaps |
| `docs/design/block-diagram.svg` | the power tree and the buses |
| `docs/design/*.pdf` | schematics and board layer plots |

Your answer goes into `docs/review/reviews.yaml`, and nothing downstream is
marked done without it. If Claude later changes something you signed off, that
review goes stale and it has to come back and ask again.

## Before you start: the environment

The plugin's skills are useless without the toolchain behind them. This repo
needs a Claude Code cloud environment built from
[MakeHardware's `env/`](https://github.com/Harwasch/MakeHardware/tree/HEAD/env) —
network access **Full**, the environment variables file, and the setup script.

The setup script is not optional. `.claude/settings.json` declares the plugin
but does not install it: in a cloud session a repo-declared marketplace is
ignored for an untrusted folder, so the setup script installs the plugin at
user scope. Without it you get a repo with no skills in it.

See [docs/01-environment.md](https://github.com/Harwasch/MakeHardware/blob/HEAD/docs/01-environment.md).
