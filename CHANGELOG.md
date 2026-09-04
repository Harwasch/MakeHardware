# Changelog

The version in `.claude-plugin/marketplace.json` and
`plugins/makehardware/.claude-plugin/plugin.json` is what a client uses to
decide whether it has an update to install. If it does not move, an existing
install treats `claude plugin marketplace update makehardware` as nothing to
do and keeps running the old code. So every change to `plugins/makehardware/`
bumps it, and `tests/version-bump.sh` fails the build when it does not.

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
