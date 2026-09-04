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

## Before concluding that an approach cannot work, list the levers you did not vary

A negative result from one configuration is a result **about that
configuration**. Corner sweeping covers tolerance, temperature and supply; it
does not cover the geometry and topology choices, which are usually the real
levers and are usually the ones held fixed without anyone noticing.

A coil analysis tested a single-layer etched spiral, found it 70 W short, and
wrote up *"PCB coils cannot reach the efficiency the thermal path requires"*.
Parallel layers — the obvious lever — were never modelled. Six layers turn a
190 W failure into a 73 W pass. The headline finding of the project was wrong
for two days.

So whenever a simulation says an approach fails, write the sentence out
before you write the conclusion:

> Held fixed: single layer, 35 µm copper, 2 mm trace pitch, 120 kHz.
> Not varied: layer count, copper weight, pitch, frequency, core material.

Then either vary the one most likely to move the number, or state the
conclusion at the scope you actually tested — "a single-layer 35 µm spiral
falls 70 W short", not "PCB coils cannot do this". The two sentences send a
project in completely different directions.

This is also why requirements are written against physics rather than against
a named conductor. A requirement phrased in terms of k·Q and dissipation
survives this correction; one that names "PCB coil" has to be rewritten, and
everything below it with it.

## Turning a run into evidence

A simulation closes a requirement only when it is reproducible, **and it is
evidence only once a human can read it**. Numbers go into a markdown table in
`docs/design/`, committed, with the failing corner first — a `.raw` file is
not a result and a plot with no number beside it is decoration. See
`hw-review` for the shape of a simulation review.

Commit the deck, record the result, and link them:

* commit the `.cir` / `.asc` under `sim/`
* put the number and the run into the requirement's `EVIDENCE` field
* add a `File` relation from the requirement to the deck
* move `STATUS` to `Verified`

Then `scripts/req_trace.py` will stop counting it as a gap. If it still does,
believe the tool.

## Turning a run into something a human will look at

The numbers go in a markdown table in `docs/design/`, committed. The *shape*
goes in a chart beside them, generated from the same rows:

```bash
hw-chart corners docs/design/standby-corners.csv \
    --out docs/design/standby-corners.svg --title "Standby current"
hw-chart bode docs/design/loop.csv --out docs/design/loop-gain.svg
hw-chart trace docs/design/startup.csv --out docs/design/startup.svg \
    --mark "x=1.2e-3,label=regulator enable"
```

`corners` is small multiples on one shared scale with the spec line drawn and
the failing corner marked — which is what makes corner evidence readable at a
glance, and what makes nominal-only evidence look as thin as it is. `bode`
computes the crossover and both margins from the data rather than taking them
from a caption. See `hw-visuals`.

Lead the summary with the corner that fails, never with the average.
