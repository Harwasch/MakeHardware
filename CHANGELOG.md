# Changelog

The version in `.claude-plugin/marketplace.json` and
`plugins/makehardware/.claude-plugin/plugin.json` is what a client uses to
decide whether it has an update to install. If it does not move, an existing
install treats `claude plugin marketplace update makehardware` as nothing to
do and keeps running the old code. So every change to `plugins/makehardware/`
bumps it, and `tests/version-bump.sh` fails the build when it does not.

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
