# How you actually do a hardware project with this

## The two repos

Nothing about a hardware project lives in MakeHardware. This repo is a
**toolbox**; each project is its own repo that picks the toolbox up.

```
Harwasch/MakeHardware                 Harwasch/thermal-probe
(this repo — the toolbox)             (a project — the actual work)

skills:   how to run each stage       plan.yaml       the work and its order
commands: /hw-new-project             requirements/   what it must do
bin:      plan-render, req-trace  ──► cad/  hw/  sim/ the design
practices: house standards            docs/           reference, design, user
env/:     the machine setup           concepts/       vision models
```

You do the work in `thermal-probe`. It borrows every skill, command and tool
from MakeHardware at session start. When you improve a practice here, every
project picks it up on its next session — which is the whole point of it being
separate.

---

## What "plugin" means, concretely

A Claude Code **plugin** is a folder of files that teaches Claude things and
gives it tools. It contains:

* **skills** — instructions Claude loads when a task matches. `hw-planning`
  loads when you talk about project planning.
* **commands** — slash commands you type. `/hw-new-project`, `/hw-status`.
* **bin/** — real executables that get added to `PATH`. In any project with
  this plugin, `plan-render` and `req-trace` just work as commands.
* **hooks** — things that run automatically, e.g. at session start.
* **.mcp.json** — the MCP servers to connect (Konnect, spice, build123d).

A **marketplace** is just a repo that lists one or more plugins. MakeHardware
is a marketplace containing one plugin, also called `makehardware`.

The reason to use this mechanism rather than copying files into each project:
**a project repo declares the plugin in four lines, and Claude installs it at
the start of every session.** You never copy skills around, and you never have
five projects running five different versions of your house practice.

---

## One-time: build the environment

In [claude.ai/code](https://claude.ai/code), create a **new** cloud environment
(don't reuse Default — this one installs KiCad and a CAD toolchain):

| Field | Value |
|---|---|
| **Network access** | See [docs/01-environment.md](01-environment.md) — this choice decides what is feasible |
| **Environment variables** | paste [`env/environment-variables.env`](../env/environment-variables.env) |
| **Setup script** | paste [`env/setup.sh`](../env/setup.sh) |

It builds once (~4 min), then gets snapshotted and reused. Every project
session afterwards starts with the whole toolchain already on disk.

---

## One-time per project: bootstrap the repo

Create the project repo with **exactly one file** in it:

`.claude/settings.json`
```json
{
  "extraKnownMarketplaces": {
    "makehardware": {
      "source": { "source": "github", "repo": "Harwasch/MakeHardware" }
    },
    "kicad-happy": {
      "source": { "source": "github", "repo": "aklofas/kicad-happy" }
    }
  },
  "enabledPlugins": {
    "makehardware@makehardware": true,
    "kicad-happy@kicad-happy": true
  }
}
```

[kicad-happy](https://github.com/aklofas/kicad-happy) is a separate MIT plugin
that adds deep read-only KiCad analysers (EMC pre-compliance, thermal, voltage
derating, datasheet cross-reference) and distributor search. It complements
Konnect rather than competing with it — Konnect *changes* the design, kicad-happy
*reviews* it. The precedence table is in the project's `CLAUDE.md`.

This file has to exist *before* the first session, because Claude reads it at
session start to decide what to install. Commit and push it.

Then start a cloud session on that repo, in the environment you just built, and
run:

```
/hw-new-project
```

That scaffolds `plan.yaml`, `requirements/`, `cad/`, `sim/`, `docs/` and a
project `CLAUDE.md`, and runs `hw-doctor` so you know up front what the
toolchain can do.

---

## Then: one session per chunk

The rhythm is **one session per chunk of work**, and the plan is what keeps
sessions from stepping on each other.

### Session 1 — Vision

> "I want a handheld probe that logs temperature in a walk-in freezer for a
> week on one charge."

Claude interviews you on the things that change the architecture — where it's
held, power source, the one number that must be true, volume, anti-goals,
regulatory. Then it builds two or three concepts as build123d models, renders
them, styles them, and publishes a vision board.

**You look at pictures and say which one, and why.** That reason is the most
valuable thing produced in this session. Agreed intent gets written as `VIS-*`
entries in your words.

### Session 2 — Plan

Claude proposes the chunks of work and their dependencies, and renders the
Gantt into your README.

**You check two things:** is that all the work (test, documentation and
manufacturing are the ones people forget), and is the order right (you usually
know a constraint Claude doesn't — a part you already have, a supplier lead
time, a review you must pass).

This is where you decide the project is mechanical-only, or
mechanical + electrical + firmware + test.

### Session 3 — Requirements

Vision becomes testable requirements with numbers and units, decomposed so
every one traces to something you asked for. `req-trace` refuses orphans and
dangling parents.

**You argue about numbers here, where it's cheap.**

### Sessions 4…N — One chunk each

Each session starts the same way:

```
/hw-status
```

which tells you what's blocked, what's ready to start, and where requirements
coverage stands. You pick a ready chunk — or say "take the next one" — and
Claude does it: schematic capture, enclosure geometry, a simulation, a
firmware skeleton.

At the end of the session Claude sets that chunk to `done`, re-renders the
plan, and commits. Your README always shows current state.

### Along the way — friction log

Whenever you correct Claude, or something takes far more loops than it should,
Claude appends three lines to `docs/design/friction-log.md` naming the
MakeHardware file that should change. It costs nothing during the work and it
is the raw material for the next section.

### Final sessions — Verification

Every requirement gets closed against evidence, or it doesn't close. The gate
exits non-zero while gaps remain, and Claude reports the number it prints
rather than a summary impression.

---

## Who does what

| Claude does | You do |
|---|---|
| Asks the questions that change the architecture | Answer them, and say what you *don't* want |
| Builds concepts and renders them | Pick one, and say why |
| Proposes chunks and dependencies | Say what's missing and what's out of order |
| Writes requirements with numbers | Argue about the numbers |
| Designs, simulates, documents | Review the diff, and the ADRs |
| Reports coverage and gaps honestly | Decide when it's good enough to build |
| Fetches datasheets where it can | Supply the ones behind a login or a paywall |

The pattern: **Claude proposes with evidence, you decide.** The three
checkpoints — vision, plan, requirements — exist because a wrong answer there
is expensive, and a five-minute conversation prevents it.

---

### End of project — Retro

```
/hw-retro
```

Claude reads the friction log, compares plan estimates against what actually
happened, and finds requirements that moved after they were agreed. It writes
`docs/design/retro.md` where **every entry names the MakeHardware file it would
change and what the edit is** — an observation without a named file doesn't go
in, because "communication could be better" improves nothing.

Then it offers to file those as issues on MakeHardware, one per change. You
review and apply them. That's the loop closing: work on project N makes
project N+1 better.

## Improving the toolbox as you go

When Claude picks a connector you don't like, tell it. The `hw-sourcing` skill
instructs it to write your preference into
`plugins/makehardware/skills/hw-sourcing/references/connectors.md` **in the
same session**, with the reason.

That's a change to *this* repo, not the project. Push it, and every project
follows the new rule from its next session onward. The same applies to any
other practice: a component-search philosophy, a preferred stackup, a review
checklist. This is how the toolbox gets sharper instead of you repeating
yourself.
