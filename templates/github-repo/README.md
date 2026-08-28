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

That scaffolds `plan.yaml`, `requirements/`, `hw/`, `cad/`, `sim/` and `docs/`
from the plugin's current templates, then runs `hw-doctor` so you know what the
toolchain can actually do before you plan around it.

Then start the vision interview:

```
Use hw-vision. I want to build <one sentence>.
```

## The commands you will use

```bash
hw-doctor                 # what the toolchain can actually do right now
/hw-status                # plan progress, what is ready to start, requirements coverage
plan-render               # refresh docs/plan.svg and the block above
block-diagram             # refresh the architecture diagram and power budget
block-diagram --check     # architecture gate; exit 1 on an over-budget rail
req-trace --gate          # traceability gate; exit 1 while gaps remain
```

## Before you start: the environment

The plugin's skills are useless without the toolchain behind them. This repo
needs a Claude Code cloud environment built from
[MakeHardware's `env/`](https://github.com/Harwasch/MakeHardware/tree/main/env) —
network access **Full**, the environment variables file, and the setup script.

The setup script is not optional. `.claude/settings.json` declares the plugin
but does not install it: in a cloud session a repo-declared marketplace is
ignored for an untrusted folder, so the setup script installs the plugin at
user scope. Without it you get a repo with no skills in it.

See [docs/01-environment.md](https://github.com/Harwasch/MakeHardware/blob/main/docs/01-environment.md).
