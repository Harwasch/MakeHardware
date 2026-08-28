# Working in this repository

This repo drives hardware design. The cost of a confident wrong answer here is
a fabricated board or a moulded part, so the bias is toward checking.

## Toolchain

The hardware toolchain lives in `/opt/hw-py` and on `PATH` via wrappers. Run
`scripts/hw-doctor.sh` first if anything behaves unexpectedly — it reports what
the environment build actually managed to install, from
`/opt/makehardware/status.json`.

* Python for CAD/analysis: `/opt/hw-py/bin/python`
* Simulation: ngspice by default, through the `spice` MCP server
* KiCad: `kicad-cli` headless; `hw-kicad-up` only when live IPC is needed
* Requirements: `/opt/hw-py/bin/strictdoc`

Do not `pip install` into the system Python. Use `/opt/hw-py`.

## Stage skills

Four skills cover the workflow — `hw-vision`, `hw-requirements`,
`hw-simulation`, `hw-verification`. Konnect installs its own KiCad skills
(`kicad-schematic`, `kicad-pcb`, `kicad-manufacture`, `kicad-review`,
`kicad-library`) under `~/.claude`; prefer those for KiCad mechanics.

## Rules that matter

**Never mark a requirement `Verified` without evidence.** All four of:
verification method, an `EVIDENCE` pointer someone can look at, a `File`
relation to the artefact, and evidence at the corners — not just nominal. An
unmet requirement reported plainly is a normal outcome. One marked Verified is
a hidden defect.

**Report what the gate says.** `scripts/req_trace.py --gate` exits 1 while gaps
remain. If coverage is 60%, say 60%. Do not call a design complete while it is
failing.

**Cross-check simulations against closed form** wherever one exists, and read
the `observations` field — ngspice prints `singular matrix` and then writes
plausible numbers anyway.

**Requirements need a parent.** If you cannot name the parent for a new
requirement, nobody asked for it. Raise it with the human rather than
inventing one.

**Numbers and units, always.** "Low power" is not a requirement; "<= 40 uA in
standby" is. Put the reasoning in `RATIONALE` — it is what gets re-read when
the number has to move.

## Gotchas that have already cost time

* StrictDoc multi-line fields need `>>>` / `<<<` blocks, and bodies render as
  RST — a bare `SYS-*` breaks the build on an unterminated emphasis span.
  Write ``` ``SYS-`` ```.
* ngspice `.meas` at deck top level rejects LTspice's `vdb()`. Put the analysis
  and measurement in a `.control` block.
* `ccx -v` exits 201 on success. Check its output, not its exit code.
* `apt-get update` exits 0 even when a repository is blocked by the egress
  policy. Assert the version you actually got.
* The environment snapshot preserves files, not processes. Anything that must
  be running goes in `scripts/session-start.sh`.

## Publishing

Vision boards, traceability reports and anything else the human will act on or
share should be published as an Artifact, with the images and the numbers
together. Lead with gaps, not percentages.
