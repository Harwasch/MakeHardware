# Changelog

The version in `.claude-plugin/marketplace.json` and
`plugins/makehardware/.claude-plugin/plugin.json` is what a client uses to
decide whether it has an update to install. If it does not move, an existing
install treats `claude plugin marketplace update makehardware` as nothing to
do and keeps running the old code. So every change to `plugins/makehardware/`
bumps it, and `tests/version-bump.sh` fails the build when it does not.

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
