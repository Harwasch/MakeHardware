# Changelog

The version in `.claude-plugin/marketplace.json` and
`plugins/makehardware/.claude-plugin/plugin.json` is what a client uses to
decide whether it has an update to install. If it does not move, an existing
install treats `claude plugin marketplace update makehardware` as nothing to
do and keeps running the old code. So every change to `plugins/makehardware/`
bumps it, and `tests/version-bump.sh` fails the build when it does not.

## 0.11.0

The design loop was a diary. It is now a loop.

### Fixed

* **Every number on an evolution chart was typed in by the agent.**
  `hw-iterate record` took metrics on the command line, so each figure had
  been read off a simulator's output and retyped — a transcription, unchecked,
  of a number nobody could re-derive. `--evidence` named the file it came from
  and nothing ever opened that file. The chart looked like evidence and was
  testimony.

  That broke this repository's second founding rule, in its newest subsystem:
  *"Generated, not hand-written. Every number on a review page is read from
  the file that owns it. If you find yourself typing a figure into markdown
  that a tool could compute, that number is already wrong — it just does not
  know it yet."*

* **A pass that met its target by breaching a `--track` limit recorded as a
  clean `pass`.** `--track` exists precisely because an objective alone is a
  licence to wreck everything else to satisfy it, so the one trade the loop is
  open to catch was the one it recorded as a success. A derived verdict now
  downgrades it to `partial` and names the breached limit on the console.
  Found by rebuilding the worked example and reading the chart, not by reading
  the code.

* **"Best" meant best on the objective, breaches included.** It now means best
  among the passes that respected their limits, falling back to the overall
  best when none did. The verdict already carries the breach, so the chart and
  the ledger apply the same rule.

### Added

* **`hw-iterate run`** — executes the verifier, keeps its output as the
  evidence file, reads each number out with a named extractor, and records the
  pass. One call where there were four, and no figure passes through anyone's
  hands. The verdict is derived from the objective against its target and the
  tracked limits; `--verdict` overrides it for the case where the number is not
  the whole story.

* **`hw-extract`** — the extractors, usable on their own to get a spec right
  before wiring it into a loop:

  | | reads |
  |---|---|
  | `meas:NAME` | an ngspice `.meas` or `print` line — measured against ngspice 42, both forms |
  | `line:PREFIX` | the number after a literal prefix, e.g. Elmer's `ElectroMagnetic Field Energy:` |
  | `json:a.b.0.c` | a dotted path — build123d `measure()`, `req-trace --json` |
  | `csv:COL[:how]` | a column reduced by `last`/`first`/`max`/`min`/`mean`/`absmax` |
  | `re:PATTERN` | first capture group, for anything else |

  Every extractor fails loudly when its metric is absent. A loop that silently
  records nothing for a missing measurement is worse than one that stops,
  because the chart still draws and the gap does not show. `run` refuses to
  record a pass whose objective could not be read, rather than recording a
  hole.

* **`hw-iterate verify`** — re-derives every recorded number from the file it
  was read out of, and `status --gate` now fails on a figure that no longer
  reproduces. A deck edited after the run, an extractor that changed meaning, a
  number someone typed: all of it surfaces here instead of on a review page.
  Passes recorded by `record` carry no extractor and are reported as
  unverifiable rather than as wrong — `record` remains right for a bench
  reading or a scope photograph.

### Changed

* **The worked example's standby loop is now driven by `run`.** Its five
  passes come from a stand-in model that emits ngspice's own `.meas` format —
  the same convention `build-fixture.py` already uses for the vision renders —
  so `run` and `verify` take exactly the path they take against a real
  simulator. The run logs are committed, which is what lets `verify` pass on a
  fresh clone. Two of the five passes now read `partial`: they hit the current
  target by breaking the wake-up budget, which is the trade the whole chart
  exists to show.

## 0.10.0

`hw-repair` could repair two of the seven things `setup.sh` installs, and
`hw-repair kicad` installed the skill pack rather than KiCad. The phase most
likely to fail was the one it could not touch at all: `phase_python` pulls
`cadquery-ocp`, a ~400 MB wheel and by far the most likely thing in the build
to time out. A session learned its toolchain was broken and could do nothing
but wait for somebody to rebuild the environment.

### Added

* **`hw-repair python [group]`** — re-run one of `phase_python`'s install
  groups. The groups exist so one flaky dependency cannot take out the rest;
  this finishes the thought by letting a session re-run the one that failed.
  `hw-repair python` with no argument lists which groups import and which do
  not; `all-groups` does every missing one.

  It is more likely to work than the build was: the five-minute snapshot
  budget does not apply to a session, which is exactly the constraint that
  makes cadquery-ocp time out at build time.

  Three refusals, all deliberate. It **will not `uv venv`** — recreating
  `/opt/hw-py` to fix matplotlib would throw away a working strictdoc, and
  that is a rebuild, not a repair. It **resolves `uv` explicitly** across
  `/root/.local/bin` and `/root/.cargo/bin` and fails loudly when it is
  absent, with **no pip fallback**, because `uv venv` creates a venv without
  pip and `python -m pip` then fails with an error that explains nothing. And
  it **verifies by import**, not by exit code — a resolver can succeed and
  leave an import broken, which is a different problem with a different fix.

* **`hw-repair base`** — re-install `phase_base`'s package set.

* **`env/bootstrap.sh`** — bring a container up from nothing.

  Not a `hw-repair` subcommand, and it cannot be one: `hw-repair` ships inside
  the plugin, so a container bare enough to need a bootstrap does not have it.
  The only entry point that works from nothing is a URL, so that is what it is:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/Harwasch/MakeHardware/main/env/bootstrap.sh | bash
  ```

  It installs `uv` if the container lacks it, fetches the same `setup.sh`, and
  runs it with KiCad and magnetics off unless you pass `--full` — those are
  minutes each and both need `ppa.launchpadcontent.net`, and failing there
  should not cost you the Python environment too. This is the Codex path,
  where the plugin manifest imports but there is no environment dialog and no
  setup-script field, so the skills arrive and the tools they name do not.

* **`tests/python-groups.sh`** — `setup.sh` and `hw-repair.sh` still agree
  about what installs what.

  They cannot share a definition: `setup.sh` is pasted into the environment
  dialog as one self-contained file and cannot source anything from this repo,
  while `hw-repair.sh` ships inside the plugin. So the tables are duplicated
  and checked instead of hand-synced, which is the same answer
  `tests/version-bump.sh` gives for the two version files.

### Changed

* **`phase_base` installs `socat`.** `claude plugin eval` runs any Bash it
  grants under an OS sandbox and needs bubblewrap *and* socat. `bwrap` is in
  the image; socat was not, and without it every sandboxed run refuses rather
  than running unconfined — which reads as the eval being broken rather than
  as a missing package.

* **`phase_plugin` merges the permission allowlist into
  `/root/.claude/settings.json` at user scope.** This is the fix 0.9.0 could
  not make. A cloud session has no trust dialog, an untrusted workspace
  ignores project-scope `permissions.allow` entirely, and so the three
  checked-in `settings.json` files — the ones 0.9.0 corrected — do nothing
  there. This is the copy that is actually read.

  Merged with `jq`, never overwritten: that file may already hold the user's
  own settings, and clobbering those to add a convenience is a bad trade. A
  file that does not parse is left alone rather than replaced.
  `tests/settings-allowlist.sh` now checks this fourth copy of the list too,
  including that `hw-repair` stays out of it.

* **`hw-repair` says where the line is, and `hw-doctor` and the docs agree.**
  A repair reaches anything consumed by a **subprocess it spawns** — apt
  packages, Python packages, cloned repos, `/usr/local/bin`. It reaches
  nothing consumed by the **session's own tool registry** — MCP servers,
  skills, slash commands, `bin/` on PATH, environment variables — because
  those are read once at session start.

  That distinction is why `hw-repair python cad` now prints, in as many
  words, that it fixed `build123d` for scripts and did **not** fix the
  build123d MCP server, which lives in its own venv and whose process started
  with the session. Without the line, the agent repairs, sees no MCP tools,
  and concludes the repair failed when it did not.

  `hw-repair bootstrap` is a recognised argument purely so it can explain
  why it does not exist and point at `env/bootstrap.sh`.

## 0.9.0

The loop back to this repository had no plumbing in it. `hw-retro` has told the
agent to "offer to file the proposed changes as a GitHub issue on
`Harwasch/MakeHardware`" since 0.5.0 and never named a mechanism, because there
isn't one: `gh` is not in the environment, and a cloud session's GitHub token is
scoped to the project repo, so it cannot reach this one at all. Every retro that
ever ran finished by offering something impossible.

### Added

* **`hw-feedback`** — a finding about the toolbox becomes a record here and an
  issue there.

  The design decision worth arguing with: **an issue tracker is the right place
  to publish a finding and the wrong place to capture one.** Issues are good at
  what nothing else gives free — evidence accumulating on one finding,
  discussion, labels, search, PR linkage. They are bad at capture, because they
  want an account, a browser and a context switch at exactly the moment —
  mid-work, mid-correction — when a finding is cheapest to write down and most
  likely to be lost.

  So capture is local and always, and publication is batched at the retro:

  ```bash
  hw-feedback new --file skills/hw-sourcing/references/connectors.md \
      --title "Connector choice is relitigated every project" \
      --edit "Fill in the board-to-wire row with Molex PicoBlade, and say why" \
      --evidence "friction log 2026-08-28; commits a1b2c3, d4e5f6"
  hw-feedback list       # every record and its state
  hw-feedback publish    # prepare the unpublished ones
  hw-feedback mark <slug> <url>   # where it actually went
  ```

  `new` writes `docs/design/feedback/<date>-<slug>.md` in the project repo with
  no network and no credentials. `publish` prepares one issue for the batch:
  a prefilled link, a dedup search, and the body to paste. It **prepares** —
  it prints `NOT FILED` and the skill forbids the word "filed", because
  claiming an issue exists when what exists is a URL is the kind of wrong
  nobody catches until they go looking for it. Where the session does have a
  working `gh` channel to this repo, which locally it often does, it files
  directly and marks the record itself.

  Two things it does deliberately. It **inlines evidence rather than linking**
  — the project repo is usually private, so a blob URL 404s for whoever has to
  act on the finding. And it **prefills a summary, not the issue**: GitHub
  answers an over-long GET with 414 and percent-encoding inflates markdown
  1.8-3.0x, so a real finding does not fit in a URL. The form arrives
  pre-addressed and the body is pasted.

  The gate is structural and nothing more: a `--file` that resolves under the
  plugin, a non-empty `--edit`, a non-empty `--evidence`. Whether a finding is
  about the system or about one design is a judgement, it is carried in
  `hw-retro`, and a keyword classifier would get it wrong in both directions.

* **`.github/ISSUE_TEMPLATE/`** — the form `hw-feedback` prefills, plus a
  `config.yml` keeping blank issues on, because adding the directory turns on
  the template chooser for everyone filing by hand.

* **`tests/feedback.sh`** — the gate refuses an observation with no named file;
  the URL's query parameters round-trip back to the exact input text; every
  parameter names a real field `id`; the `kind` value is an exact option match;
  an oversize finding still yields a clickable link. The last three are the
  silent ones: GitHub prefills a form by matching the query parameter name
  against the element's `id`, and a name or a dropdown value it does not
  recognise renders the field blank with no error on any side.

* **`tests/settings-allowlist.sh`** — every tool in `bin/` is allowed in all
  three settings files, the three lists agree as sets, and no doc page quotes
  an entry that does not exist.

### Fixed

* **The friction log is scaffolded.** It was documented in three places —
  `docs/design/README.md`, the project `CLAUDE.md`, and `hw-retro` — and
  created by nothing, so `/hw-retro` step 1 read a file that never existed.
  `templates/project/` now carries it, along with `docs/design/feedback/`, and
  `tests/smoke.sh` asserts both survive a scaffold.

* **Six tools were missing from every allowlist.** `sch-lint`, `pcb-lint`,
  `hw-chart`, `cad-export`, `review-artifact` and `hw-iterate` — which is to
  say every gate added after the list was first written — prompted for
  permission on every call. The cost was not one prompt: the gates are what an
  agent runs most often, so the omission taxed exactly the workflow the gates
  exist to enforce.

  `hw-repair` is deliberately **not** added. It writes apt sources, imports GPG
  keys and installs packages as root; the prompt is the review. The test
  asserts it stays out, with the reasoning in its header, so the omission does
  not get "fixed" later.

  Worth knowing what this does not fix: a cloud session's workspace is
  untrusted, and an untrusted workspace ignores project-scope
  `permissions.allow` entirely. The durable fix is at user scope from the
  setup script, and it is not in this release.

* **`KI_STACK_DIR` is gone from `env/environment-variables.env`.** It belonged
  to ki-stack, the pack 0.8.0 replaced, and pointed into `/opt/ki-stack` —
  which `hw-repair kicad` now deletes as a leftover. Anyone pasting the current
  file into a new environment was setting a variable aimed at a directory the
  repair tool treats as stale.

  Removing it only helps environments built from here on. That file is pasted
  into the environment dialog once and the dialog is the source of truth
  afterwards, so an environment that already sets it still does. `hw-doctor`
  now says so when the path does not exist, which is the only thing that
  reaches a running session.

### Changed

* `scripts/_gh.py` — `repo_slug`, `head_ref`, `blob_url` and `uncommitted`
  moved out of `review_gate.py`, which imports `yaml` at module level.
  `hw_feedback.py` is stdlib-only on purpose: it is the tool you reach for
  *because* the Python environment degraded, so depending on `/opt/hw-py`
  having landed would make it fail in exactly the session that produced the
  finding. `review_gate` re-exports them, so `plan_render` and
  `review_artifact` are unchanged.

## 0.8.0

The KiCad skill pack is now [KiStack](https://github.com/American-Embedded/KiStack)
(American Embedded) rather than [ki-stack](https://github.com/Milind220/ki-stack)
(Milind220). Both are skills, not servers, so the argument in 0.7.0 stands
unchanged — this is a choice between two skill packs, not a change of
architecture.

### Changed

* **KiStack replaces ki-stack.** They are different books. ki-stack is a manual
  for the *substrates* — how to route between live IPC, `kicad-cli` and
  structured file edits. KiStack is house practice from a working shop: what a
  good schematic looks like, how to place before routing, when a pin swap is
  worth it, how to read a Gerber. This toolbox already answered the substrate
  question in `hw-schematic` and `hw-pcb-layout`; what it did not have was the
  craft.

  Ten skills — `kicad-schematic`, `kicad-pcb`, `kicad-layout`, `kicad-symbol`,
  `kicad-footprint`, `kicad-bom`, `kicad-export`, `kicad-gerbers`,
  `kicad-panelize`, `pcb-product-render` — plus a reference page for every
  `kicad-cli` verb, which is the fastest way to get an export flag right.

* **A conflict table, because there is a real conflict.** KiStack overlaps
  `hw-schematic` and `hw-pcb-layout` and disagrees with them in places. The
  rule is **the gate wins** — `sch-lint`, `pcb-lint` and `review-gate` are what
  actually fail a stage, and advice that reads well while failing a gate is not
  shippable. `hw-schematic/references/kicad-channels.md` names the three
  collisions:

  - **Sheet strategy.** KiStack prefers one big sheet you can see at once; this
    toolbox derives a sheet plan from the agreed block diagram. Take the sheet
    plan: `sch-lint --plan` binds every sheet to an architecture a human signed
    off, and a single huge sheet does not render on the review page.
  - **Changing the schematic during layout.** KiStack says do the pin swaps.
    Correct — and `review-gate` will mark the schematic review stale, which is
    also correct. Do it, then re-open the review.
  - **Autorouting.** No conflict; both say manual first.

  One that people expect to collide and does not: KiStack's 50 mil label text
  is exactly the house `text_size_mm: 1.27` that `SCH-TEXTSIZE` checks.

* Skills are linked under their **frontmatter** names, not their directory
  names — `skills/schematic/` declares `name: kicad-schematic`, and frontmatter
  is what the agent sees.

### Fixed

* **`hw-repair kicad` no longer eats the pack it just installed.** Konnect
  shipped skills called `kicad-schematic` and `kicad-pcb`; so does KiStack. The
  leftover cleanup matched on filename, which would have deleted the new pack
  along with the old one. Those two names are now matched on **content** —
  only Konnect's own skills mention Konnect — and `tests/smoke.sh` covers it
  with a fixture that fails if the check ever regresses to name matching.

* `hw-repair kicad` also clears ki-stack's 0.7.0 leftovers: its nine
  `ki-stack-*` skills, its twelve `/usr/local/bin` wrappers (which pointed into
  a clone about to be deleted), the clone itself, and the `KI_STACK_DIR` export
  in `.bashrc`. Measured on this container: 22 leftovers removed.

## 0.7.0

Konnect is out; [ki-stack](https://github.com/Milind220/ki-stack) is in. The
plugin no longer ships a KiCad MCP server at all.

### Changed

* **KiCad automation moved from a tool surface to a substrate.** Konnect was an
  MCP server — one Rust binary, 214 tools over KiCad 10's IPC API. ki-stack is
  nine SKILL.md files and a dozen shell helpers that teach the agent to drive
  the three real substrates itself: `kicad-python` for live IPC,
  `kicad-cli` for render/export/DRC/ERC, and `kiutils-rs` for structured
  offline file edits.

  The argument is what `kicad-cli` cannot do. It has no `add`, `place`, `route`
  or `connect` verb, so *something* has to drive the IPC API; the only question
  is whether that something is pre-sliced verbs or code the agent writes. Two
  things settled it: a tool surface costs context whether or not it is used
  (Konnect loaded 2 of its 20 toolsets at startup and made the agent fetch the
  rest, which failed in ways that read as "the tool is missing"), and a missing
  tool is a wall where a skill that names its fallback is a route — the same
  reasoning `hw-optimize` already applies to everything else.

  **What it costs:** Konnect's design-review audits and its manufacturing
  pipeline have no ki-stack equivalent. `sch-lint`, `pcb-lint`,
  `hw-verification` and kicad-happy already covered most of that ground, which
  is why the loss is acceptable — but it is a loss, not a wash.

* **The rule about editing `.kicad_*` files changed shape.** It was "nothing
  writes one except KiCad or Konnect". It is now "nothing writes one except
  KiCad, its IPC bindings, or a structured parser that round-trips it".
  Parser-backed offline edits are a first-class route now, and for schematic
  work usually the better one. Hand-rolled S-expression edits — `sed`, a regex,
  a string replace — are as forbidden as they ever were, and for the same
  reason: the file still opens and the netlist is quietly wrong. The
  distinction is structural versus textual, not tool versus file.

* **`MH_ENABLE_KONNECT` is now `MH_ENABLE_KICAD`.** The old name is still
  honoured, so an environment carrying it keeps working rather than silently
  losing KiCad. `MH_KONNECT_FROM_SOURCE` is gone — nothing is built from source
  any more, which also drops `cmake`, `pkg-config` and the protobuf toolchain
  from the base packages.

* `templates/kicad/konnect-house.json` is now `house-defaults.json`, merged
  into the project's `.kicad_pro` (plain JSON) rather than loaded through an
  MCP call.

### Added

* **`hw-repair kicad`** — installs ki-stack and deletes the Konnect leftovers.
  This is the important half of the migration: an environment built before
  0.7.0 still carries Konnect's six skills and two agents in its snapshot, and
  they are worse than absent. They tell the agent that every `.kicad_*` change
  MUST go through MCP tools that are no longer registered, so it reads a
  missing tool as a broken environment and stops, instead of reaching for the
  `kicad-cli` and IPC bindings sitting right there. `hw-doctor` flags the
  leftovers and names the command.

### Fixed

* **A wrapper generator that ate the thing it wrapped.** The first cut of the
  ki-stack phase wrote `/usr/local/bin/<helper>` with `cat >`, over a path a
  previous install had left as a symlink into the clone. `cat >` follows a
  symlink, so the wrapper landed *inside* the upstream script as an `exec` of
  itself — an infinite loop that hung the build with no error at all. `rm -f`
  before the write. Caught by running the phase twice.

* Seven ki-stack helpers locate the pack with `dirname "${0}"/../../..`, which
  under a symlink in `/usr/local/bin` resolves to `/`. They are installed as
  wrappers rather than symlinks so `ki-stack-version` and `kicad-render` work
  from any directory.

## 0.6.0

### Removed

* **The Onshape FeatureScript MCP server**, added one release ago in 0.5.0.
  The server entry is out of `.mcp.json`, the `onshape` section is out of
  `hw-cad`, `fs-mcp.labs.onshape.app` is out of the allowlist, and the
  reachability probe is out of `hw-doctor`. `build123d` was already the
  default CAD path and is unaffected — nothing else in the toolbox depended on
  Onshape.

  A minor bump rather than a patch: anyone who installed 0.5.0 and started
  calling the `onshape` tools loses them, and 0.x treats that as breaking even
  when the window was hours. Rebuild the environment to drop it; a session on a
  0.5.0 snapshot keeps the server until then. If you kept
  `fs-mcp.labs.onshape.app` on a Custom allowlist, it is now dead weight rather
  than a problem.

  This removes the *plugin's* wiring only. An Onshape connector attached to a
  claude.ai account is a separate thing and is untouched.

## 0.5.0

Two tools that had never worked, one that failed for a reason nobody had
looked at, a CAD path the human can open in a browser — and the loop itself:
an agent iterating toward a target now leaves a record a reviewer can check
instead of a number they have to trust.

### Fixed

* **Elmer had never installed. In any session, in any environment.** The
  pinned tarball URL — a release asset on this repository — 404s, and always
  did: there are no releases on this repository at all. `phase_magnetics`
  degraded on every build, and because a degraded phase still exits 0 the
  environment came up looking healthy with no `ElmerSolver` in it. It now
  installs `elmerfem-csc` from the upstream elmer-csc PPA, which is on
  `ppa.launchpadcontent.net` — the host KiCad 10 already needs, so it costs no
  new allowlist entry. Verified end to end: v26.2, ~70 s, and a coupled
  magnetostatic/thermal/stress solve of `CoilOnIronCore` in 16 s. The packaged
  build is self-contained, so the `LD_LIBRARY_PATH` export the old one needed
  is gone from both the setup script and the `hw-magnetics` skill.

* **Konnect's two subagents launched with no tools.** `konnect init` writes
  them with `tools: [mcp__konnect__*]`, which is right for a standalone
  install and wrong for ours: Claude Code namespaces a plugin's MCP servers,
  so under this plugin every Konnect tool is
  `mcp__plugin_makehardware_konnect__*` and that glob matched nothing. The
  agents did not error — they came back having "reviewed" a board they could
  not open, which is the worst shape a failure can take. Both patterns are now
  written, at build time and by `hw-repair konnect` for environments already
  snapshotted with the broken files.

* **`hw-doctor` reported build123d as failed when it was fine.** Its first
  import pulls in OCCT and takes ~25 s cold; the probe timeout was 20 s, so
  the one command whose job is to say whether the toolchain works said the CAD
  stack was broken. Ceiling raised to 45 s.

* **An ad-hoc review showed its questions and none of its evidence.** A review
  with no `STANDARD` phase of its own — a design loop, a simulation campaign —
  rendered its title, summary and questions on the review page and dropped its
  artefacts. They were on the markdown packet, but the page is what the
  request links to first.

### Added

* **`hw-optimize` and `hw-iterate` — the closed design loop.** An agent given
  "get the phase margin above 60 degrees without losing the bandwidth" changes
  a value, simulates, reads the number and repeats; by default none of that
  survives, and the repository ends up with the last netlist and a sentence
  claiming a figure. `hw-iterate` records every pass — the variables changed,
  the metrics measured, and the run file each number was read out of — and
  `hw-chart evolution` draws the trajectory: the objective against its target,
  each tracked metric against its own limit, and a strip of which knob moved
  when. A reviewer reads three things off it that no paragraph delivers: that
  it converged rather than stopped, which change bought the improvement, and
  what it cost elsewhere.

  `--track` is the half that matters. An objective alone is a licence to wreck
  everything else to satisfy it, and a loop that does exactly that looks like a
  success from the inside. `hw-iterate record` says when the last three passes
  are within 2% of each other — the signal to change approach rather than run a
  fourth variation of the same idea — and `status --gate` exits 1 unless the
  accepted pass meets the target and names its evidence.

* **The perseverance/escalation policy**, in `hw-optimize`. The two failure
  modes are symmetric: an agent that stops at the first obstacle wastes the
  human's time on things it could have solved, and one that never stops burns a
  day building the wrong thing confidently. The line is drawn where a
  well-informed human could reasonably disagree with either answer — that is a
  decision, and it goes to them. A missing tool, a failed solve, an approach
  that did not work: those are obstacles, and they are the agent's.

* **The Onshape FeatureScript MCP server**, at
  `https://fs-mcp.labs.onshape.app/mcp`. Claude Code runs the sign-in on first
  use, against the human's own account. build123d stays the default — it is in
  the repository, it diffs, and `cad-export --check` gates it; Onshape is for a
  live CAD document the human keeps working in, and for authoring reusable
  custom features, which build123d has no equivalent of. `hw-cad` carries the
  comparison and the warning that every call spends the account's Onshape API
  allocation.

* **`hw-repair`** — run-time repair for what the environment build missed.
  The environment is a snapshot taken once, before any session starts; when a
  phase degrades, every session made from it is missing the tool and the clean
  fix is a rebuild that an agent mid-task cannot do. `hw-repair elmer` is
  ninety seconds. `hw-doctor` now names it where it would help.

* **`hw-schematic/references/kicad-channels.md`** — which of Konnect,
  `kicad-cli` and the lint tools may touch a `.kicad_*` file, and the recovery
  list to work before escalating a Konnect failure. It also answers the
  recurring question with a fact: `kicad-cli` has no `add`, `place`, `route` or
  `connect` verb on KiCad 10, so there is no direct CLI to use instead of
  Konnect. Konnect authors; `kicad-cli` exports and checks, and you may call it
  yourself for those.

### Changed

* **`review-gate` now enforces concision.** A 60-word budget on `--summary`, 25
  on each question, and 80 words per viewable artefact. Over budget on the
  first two and the review is refused before the packet is written — the fix is
  always to shorten text that has not been sent yet, or to generate the figure
  that makes the words unnecessary. The worked example's five reviews run 24-46
  words of summary and 5-14 a question, and none of them are thin. `--long`
  overrides it, and every use of it is a review somebody skimmed.

* **The example project now carries a design loop.** `examples/thermal-probe`
  ends its standby write-up with "the reference could be duty-cycled ... that
  is the obvious lever and it has not been modelled". It is modelled now, as
  five recorded passes: #2 met the current target and was rejected on wake
  time, #4 was better still and rejected harder, and the accepted pass is not
  the best one on the objective. That is the shape the chart exists to show.

## 0.4.0

Drawings somebody can read, files somebody can open, and pictures instead of
paragraphs. The plugin had fourteen skills and none of them was about drawing:
Konnect will place a symbol anywhere it is told to, and nothing had an opinion
about where.

### Added

* **`hw-schematic`** and **`sch-lint`** — house practice for a readable
  drawing, and fourteen checks that measure it: the 1.27 mm grid, orthogonal
  wires, sheet density against the review page's budget, named nets, rails up
  and grounds down, one text size, hierarchical pins matching their labels,
  decoupling drawn beside the pin it serves, designators in reading order,
  and `--plan`, which binds every sheet back to the block diagram the human
  agreed to. `--svg` draws every finding on the sheet — 340 elements against
  the 60,538 KiCad's own plot of that sheet costs.

* **`hw-pcb-layout`** and **`pcb-lint`** — the prose in
  `hw-verification/references/pcb-layout.md` turned into arithmetic that runs.
  A thermal-via array landing on opposite-side copper, a net class no pad on
  its nets can accept, a clearance that violates itself inside a footprint, a
  keepout written from memory, decoupling loops ranked worst-first, silk on
  pads, unreadable designators, courtyard overlap by real polygon area, and a
  signal layer with no reference plane.

* **`hw-cad`** and **`cad-export`** — assemblies rather than one unnamed
  solid. STEP AP242 with the tree, part names, colours and a named datum at
  every joint; GLB for the review page's orbit viewer; STL for GitHub's own 3D
  viewer, the only 3D format it renders; 3MF for print; `joints.json`; a
  FreeCAD 1.0 macro that rebuilds the assembly with real, draggable joints;
  and renders assembled, exploded, sectioned and isometric. The gate fails on
  a part with no label, no colour, or no joint reaching it.

* **`hw-visuals`** and **`hw-chart`** — the seven plots the workflow needs, to
  one set of rules: direct labelling rather than a legend, the limit drawn
  beside the value, the anomaly annotated, small multiples on one shared
  scale, and state never carried by colour alone. Two to seven kilobytes of
  themed SVG each.

* **The review page became usable.** Scroll-to-zoom and drag-to-pan on every
  figure, an orbit viewer for a `.glb`, sortable tables. A plotted A4 sheet
  squeezed into a browser column is legible as a shape and unreadable as a
  document; that is the difference between a picture of a schematic and a
  schematic.

* **House KiCad templates** — an A3 drawing sheet whose every field is a KiCad
  text variable, and the grid, text sizes and net classes as Konnect config.

* **`block-diagram --summary --csv`**, so the power budget chart comes from the
  same numbers the table prints rather than from a retyped copy.

### Notes

Nine things were found by measuring rather than by reading, and each is
written down where it will be met again — the plugin's own `CLAUDE.md`, the
skill that owns it, or the script's docstring. The ones that would have
silently produced wrong output:

* **Net classes are not in the `.kicad_pcb`.** They are in the sibling
  `.kicad_pro`. A board linter written to the obvious design reports every
  board clean.
* **STEP AP242 cannot be selected from outside `build123d`.** `export_step`
  resets `write.step.schema` partway through its own body, so setting it
  returns True and changes nothing.
* **`Compound(children=[...])` reparents.** Building a second compound from an
  assembly's children empties the assembly, and every export after it writes a
  few hundred bytes of nothing.
* **KiCad's page-layout parser rejects `;;` comments**, and on a parse error
  `kicad-cli` prints one line to stderr, exits 0, and plots with the built-in
  frame.
* **Sheet size cannot be estimated from character count** — the two committed
  example sheets measure 60 and 29 SVG elements per rendered character. So
  `sch-lint` shells out to `kicad-cli` and measures; the estimate only warns.
* **GitHub's 3D viewer renders `.stl` only.** Not `.step`, not `.glb`.

## 0.3.0

Magnetics. SPICE cannot tell you an inductance; now something can.

### Added

* **`hw-magnetics`** — a skill for field simulation: which of FastHenry,
  Elmer, GetDP, Gmsh, CalculiX and magpylib answers which question, and the
  ten or so ways each of them returns a wrong answer without saying so. It is
  a separate skill from `hw-simulation` on purpose: that skill's triggers are
  circuit words, and one skill that fires on both "check the bias point" and
  "what is the coupling coefficient" would be wrong about one of them.

* **`phase_magnetics` in `env/setup.sh`** — Elmer 26.2, FastHenry 3.0.1 and
  GetDP 3.2.0. Measured at ~3 minutes, run concurrently with the KiCad and
  Python phases, and needing nothing outside the existing allowlist. Elmer
  comes from a prebuilt tarball because it is not in the Ubuntu repos and its
  PPA is off the allowlist; building it from source is ~20 minutes, which does
  not fit the build budget. `MH_ENABLE_MAGNETICS=0` turns the phase off.
  Also clones `elmer-elmag`, because `.sif` is a niche format whose failure
  mode is a solver that runs happily and reports zero — copy a working file.

* **`hw-doctor`** reports the four new tools and whether the worked `.sif`
  cases are present.

### Notes

Everything above came out of the `wpt-pcb-coils` demo in
[MakeHardwareDemos](https://github.com/Harwasch/MakeHardwareDemos), which
reverse-engineers a wireless-power coil from the physical part. Six of the
gotchas in the skill are silent-wrong-answer paths found there, including
FastHenry writing `nan` into its output while exiting 0, and an Elmer
homogenised winding behaving as turns in parallel and reporting an inductance
33 % low with the mesh fully converged.

## 0.2.0

Human review, and a review page the human actually reads.

### Added

* **`review-gate`** — the sign-off ledger. Every milestone (vision, plan,
  requirements, architecture) and every design stage records what the human
  agreed to, in their words, against the digest of the artefacts they saw. A
  tracked artefact that changes afterwards makes the review **stale** and the
  gate fails, because a sign-off against a moving target is not a sign-off.
  `plan-render --check` refuses to call a chunk `done` while its review is
  open or stale.
* **`review-artifact`** — builds `docs/review/artifact.html`, one page per
  project with a tab per phase, published as a Claude Artifact. Every figure
  and number is read from the file that owns it; nothing on the page is typed
  by hand.
  * `--init` writes `docs/review/artifact.yaml` from what the repo contains,
    with the stages whose artefacts do not exist yet commented out.
  * `--check` exits 1 naming anything it cannot show, which is much cheaper
    than the human finding out.
  * `--url` records where the page was published, so later sessions update it
    instead of creating a second page.
* **`.drawio` alongside every generated diagram**, with *Open in draw.io*
  under the picture — one click to an editable diagram, nothing to install.
* **Manufacturing release checklist** — the documents a run needs, grouped,
  with a present/missing tally. Rows for documents that do not exist yet stay
  listed, because that is the whole value of a checklist.
* **`tests/real-tool-output.sh`** — what the review page does with real
  exporter output rather than tidy fixtures.
* **`tests/version-bump.sh`** — this file's reason for existing.

### Fixed

* **An A4 schematic rendered 331 px wide.** KiCad writes the page size in
  millimetres twice meaning different things — `width="297.0022mm"` is the
  intrinsic size, `viewBox="0 0 297.0022 210.0072"` is the user-unit system —
  and the inliner preferred the viewBox.
* **SVG had no size budget.** KiCad emits one `<path>` per line segment,
  including every stroke of every character, so one dense sheet is 3.0 MB and
  61,681 elements. Now budgeted per figure and across the page, with anything
  over reported rather than silently inlined.
* **Light-background plots on a dark page.** A full-page light fill is
  detected and matted, the way an opaque raster already was. Recolouring it
  would misrepresent the artefact.
* **KiCad 10 names its layer groups** (`<g id="Wire">`), so two sheets on one
  page collided on ids that repeat in every project.
* **Power budget added child-rail currents without referring them** through
  the voltage ratio, so a 400 V rail's headroom was computed from 48 V amps.
* **Wrapped list items split into separate paragraphs**, and ordered lists
  were not supported at all — which turned an assembly traveller into one
  run-on paragraph.
* **An inlined `@media` block leaked the exporter's dark palette** onto the
  whole page and unbalanced the CSS.

## 0.1.0

First release as a plugin: the vision, planning, requirements, architecture,
sourcing, simulation, verification and documentation stages, with
`plan-render`, `req-trace`, `block-diagram`, `vision-board` and `hw-doctor`.
