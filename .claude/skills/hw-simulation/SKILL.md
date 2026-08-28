---
name: hw-simulation
description: Run and interpret circuit simulation with ngspice or LTspice through the spice MCP server. Use when a circuit needs its bias point, frequency response, transient behaviour, stability margin or noise checked, and when a simulation result needs turning into evidence against a requirement.
---

# Circuit simulation

The `spice` MCP server (ltspice-mcp) drives both simulators and parses the
binary `.raw` output, so measurements come back as numbers rather than as
something you have to read off a plot.

**ngspice is the default here.** It is headless, needs no Wine, and is a
first-class backend in this server. LTspice is only installed when
`MH_ENABLE_LTSPICE=1` — reach for it when you need vendor-encrypted ADI models
or `.asc` schematic editing, and say which simulator produced a number when it
matters.

## Dialect traps that will cost you a run

ngspice is not LTspice, and the differences bite in `.meas` first.

* `.meas` at the top level of a deck does not accept LTspice's `vdb()`; you
  get `Warning: can't parse 'vd': ignored` followed by
  `Error: no data saved`, which looks like the analysis failed rather than the
  measurement. Put the analysis and the measurement in a `.control` block
  instead, where `vdb()` works:

  ```
  .control
  ac dec 100 10 1meg
  meas ac fc when vdb(out)=-3
  .endc
  ```

* `ngbehavior = "hsa"` is set in `/etc/ltspice-mcp.toml`. That is what makes
  ngspice select the right section out of a sectioned `.lib`, which is how
  most vendor corner models ship. Without it you silently get the wrong corner.

* Per-device small-signal parameters are addressed differently:
  `.save @m1[gm]` on ngspice, `.options logopinfo` on LTspice. The server
  normalises the read-back to `m1.gm`.

## Trust the warnings, not the numbers

ngspice will print `singular matrix` once, deep in a log nobody opens, then
finish the run and write perfectly plausible numbers. The server attaches such
warnings to the value they affect in an `observations` field. **Read it.** A
result with observations attached is not evidence until you have explained
them.

The server reports facts, not verdicts. Deciding whether a number is good is
your job and the requirement's, not the simulator's.

## Sanity-check before you believe

Every simulation gets a closed-form cross-check where one exists. An RC corner
at `1/(2*pi*R*C)`, a divider ratio, a current limit. If the simulator and the
arithmetic disagree, the deck is wrong — find out which before moving on.

Sweep corners before calling anything done: component tolerance, temperature,
and supply extremes. A design that only works at nominal is not a design.

## Turning a run into evidence

A simulation closes a requirement only when it is reproducible. Commit the
deck, record the result, and link them:

* commit the `.cir` / `.asc` under `sim/`
* put the number and the run into the requirement's `EVIDENCE` field
* add a `File` relation from the requirement to the deck
* move `STATUS` to `Verified`

Then `scripts/req_trace.py` will stop counting it as a gap. If it still does,
believe the tool.
