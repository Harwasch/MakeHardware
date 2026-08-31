# Working on MakeHardware itself

This repository **is** the plugin. Projects that use it live in their own
repos and install this one; nothing here is a hardware project.

## Bump the version. Every time.

Any change under `plugins/makehardware/` must bump the version in **both**:

* `.claude-plugin/marketplace.json`
* `plugins/makehardware/.claude-plugin/plugin.json`

Not housekeeping. `claude plugin install` treats an already-installed plugin
at the same version as nothing to do, so if the version does not move, a user
who runs `claude plugin marketplace update makehardware` fetches the new
source, sees a version they already have, and **keeps running the old code** —
then debugs behaviour from code they are not running. This has already
happened once: `0.1.0` stood for twenty-nine commits across an entire new
subsystem.

```bash
tests/version-bump.sh        # fails if the plugin changed and the version did not
```

Add a `CHANGELOG.md` entry in the same commit. Semver, and this is 0.x:
additive work is a minor bump, a fix is a patch.

## Run the tests

None of them need the hardware toolchain — `python3` with `pyyaml` is enough.

```bash
tests/smoke.sh              # scaffolds a throwaway project and drives the gates
tests/real-tool-output.sh   # what the review page does with real exporter output
tests/version-bump.sh       # the release check above
```

`real-tool-output.sh` is the one that catches the expensive class of bug. The
example project's fixtures are tidy because we wrote them; real KiCad output
is not, and every hazard in that file broke the page *silently* at some point
— page size in millimetres, a `<style>` block whose selectors go global once
inlined, KiCad 10's layer-named ids colliding between sheets, a sheet with
61,681 elements in it. When you touch `review_artifact.py`, run it.

## Two rules the whole design rests on

**An artefact the human has not seen is not a deliverable.** The agent runs in
a cloud VM; the human is in a browser. Anything a review depends on has to
render on github.com or on the review page — a `.kicad_sch` or a `.step` is a
download, not a review. `review-gate` enforces this and will tell you when a
review contains nothing viewable.

**Generated, not hand-written.** Every number on a review page is read from
the file that owns it. If you find yourself typing a figure into markdown that
a tool could compute, that number is already wrong — it just does not know it
yet. The same goes for fixtures: `examples/thermal-probe/build-fixture.sh`
rebuilds everything from its specs, and the schematic sheets are genuine
`kicad-cli` output wherever `kicad-cli` exists.

## The example is the development surface

`examples/thermal-probe/` is a project caught part-way through — one milestone
approved, one awaiting an answer, one gone stale, one never requested. Change
the review page, rebuild it, and *look at it* before believing the change
worked:

```bash
cd examples/thermal-probe && ./build-fixture.sh
```
