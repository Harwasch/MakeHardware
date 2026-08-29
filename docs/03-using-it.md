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
practices: house standards            docs/           reference, design, review, user
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

The fastest way is a **GitHub template repository** — make one once from
[`templates/github-repo/`](../templates/github-repo) and every new project
starts with the file below already in place. See
[04-template-repo.md](04-template-repo.md). Note that the template supplies the
settings file only; the plugin itself still arrives from the environment's
setup script, so you still pick the right environment when you start the
session.

Doing it by hand instead — create the project repo with **exactly one file** in
it:

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

[`templates/github-repo/.claude/settings.json`](../templates/github-repo/.claude/settings.json)
is this file plus a `permissions.allow` list for the toolchain's commands
(`plan-render`, `req-trace`, `review-gate`, `kicad-cli`, `ngspice` …), so you
are not prompted for each one. Copy that version rather than the four lines
above if you want the quieter session.

Then start a cloud session on that repo, in the environment you just built, and
run:

```
/hw-new-project
```

That scaffolds `plan.yaml`, `requirements/`, `hw/`, `cad/`, `sim/`, `docs/` and
a project `CLAUDE.md`, and runs `hw-doctor` so you know up front what the
toolchain can do.

---

## Then: one session per chunk

The rhythm is **one session per chunk of work**, and the plan is what keeps
sessions from stepping on each other.

### How you get asked

Claude is running in a cloud VM. You are not at that terminal, you do not have
KiCad or draw.io, and you are not going to run a command to see the work. What
you have is **this repository on github.com, in a browser** — so that is what
the workflow is built around.

At each milestone Claude commits something that renders on GitHub, then stops
and asks you, with the link:

> Vision is ready for review — two concepts, numbers under each.
> `https://github.com/you/thermal-probe/blob/main/docs/review/vision.md`
>
> `[ Concept A — the wand ]` `[ Concept B — the instrument ]` `[ Neither ]`

You click, look, answer. Claude writes down what you said in
`docs/review/reviews.yaml` and only then moves on. If it later changes
something you signed off, the review goes **stale** and it has to come back and
ask again — which is the point: everything downstream was resting on the
version you actually saw.

You can also just browse the repo whenever you like. `docs/plan.md`,
`docs/design/vision.md`, `docs/design/requirements-map.svg` and
`docs/design/block-diagram.svg` are always current, because they are
regenerated from their specs rather than written by hand.

### Session 1 — Vision

> "I want a handheld probe that logs temperature in a walk-in freezer for a
> week on one charge."

Claude interviews you on the things that change the architecture — where it's
held, power source, the one number that must be true, volume, anti-goals,
regulatory. Then it builds two or three concepts as build123d models, renders
them, styles them, and writes `docs/design/vision.md` — the concepts side by
side with their envelopes, volumes and masses, and the open questions at the
end.

**You look at pictures and say which one, and why.** That reason is the most
valuable thing produced in this session. Agreed intent gets written as `VIS-*`
entries in your words, and the sign-off is recorded so nothing later can quietly
proceed as though you had said something else.

### Session 2 — Plan

Claude proposes the chunks of work and their dependencies, and renders the
Gantt into your README.

**You check two things:** is that all the work (test, documentation and
manufacturing are the ones people forget), and is the order right (you usually
know a constraint Claude doesn't — a part you already have, a supplier lead
time, a review you must pass).

You review `docs/plan.md` — every chunk, what it is, what it needs first, what
it produces — with the chart embedded at the top. It deliberately carries no
statuses, so your agreement survives a week of ordinary progress and only
breaks when the *work* changes.

This is where you decide the project is mechanical-only, or
mechanical + electrical + firmware + test.

### Session 3 — Requirements

Vision becomes testable requirements with numbers and units, decomposed so
every one traces to something you asked for. `req-trace` refuses orphans and
dangling parents.

**You argue about numbers here, where it's cheap.** You do it over
`docs/design/requirements-map.svg` — the whole tree on one page, an arrow from
each requirement to the one that refines it, and anything the gate is unhappy
about outlined in red. A requirement with nothing above it is visible in a
second and invisible in a list.

### Session 4 — Architecture

The electrical architecture is settled before any schematic exists: the major
ICs, the power tree with a current budget, and the data buses. Claude writes
`hw/block-diagram.yaml`; `block-diagram` renders it to an editable draw.io file
and to `docs/design/block-diagram.svg`, which shows up inline on GitHub.

**You review a picture here, not a netlist.** A missing rail or a bus on the
wrong controller is obvious on one page of boxes and nearly invisible in a
schematic. If you want to move things around, open the `.drawio` — your
positions are kept the next time it renders.

`block-diagram --check` fails if a rail draws more than its regulator can
deliver, and names the biggest contributors. That is the whole point of doing
this before layout.

### Sessions 5…N — One chunk each

Each session starts the same way:

```
/hw-status
```

which tells you what's blocked, what's ready to start, where requirements
coverage stands, and **what's waiting on an answer from you**. You pick a ready
chunk — or say "take the next one" — and Claude does it: schematic capture,
enclosure geometry, a simulation, a firmware skeleton.

Each large design stage ends the same way as the first four: a PDF of the
schematic, layer plots and a 3D render of the board, renders of the enclosure —
committed, and a question with the link. You never have to open KiCad to say
"that connector is on the wrong edge".

At the end of the session Claude sets that chunk to `done`, re-renders the
plan, and commits. It cannot mark a chunk done if the files that chunk was
supposed to produce are not there, or if you have not signed off its review —
`plan-render --check` refuses both. Your README always shows current state.

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
| Commits something you can open in a browser, and asks | Click the link and answer |

The pattern: **Claude proposes with evidence, you decide.** The four
checkpoints — vision, plan, requirements, architecture — plus one per design
stage exist because a wrong answer there is expensive, and a five-minute
conversation prevents it. They are enforced rather than encouraged: a stage
whose review is unsigned or stale fails `review-gate check --gate`, and a chunk
that depends on it cannot be marked done.

If you would rather Claude ran further ahead before checking in, say so — but
the default is to interrupt you, because the alternative is a project built on
an agreement nobody made.

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
