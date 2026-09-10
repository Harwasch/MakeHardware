---
name: hw-optimize
description: Run a design as a closed verify-and-refine loop - change a value, simulate it, read the number, change the next thing - and record every pass so the review shows how the design moved rather than only where it landed. Use whenever a target has to be met rather than merely computed (a margin, a temperature rise, a loss, a fit, a cost), whenever a first attempt misses, before reporting that a design meets a requirement, and whenever asked to optimise, tune, converge or "get it to" a number.
---

# The closed design loop

An agent handed *"get the phase margin above 60 degrees without losing the
1 MHz bandwidth"* does not solve it in one pass. It changes a value, simulates,
reads the result, changes the next thing, and repeats. That loop is where
almost all of the engineering happens — and by default none of it survives.
The repository ends up holding the last netlist and a sentence claiming a
number.

That is a bad trade for everyone:

* The human cannot tell a **converged** design from one that **ran out of
  budget**. Both report a number.
* The next session re-explores knobs this one already found useless.
* The trade the loop made is invisible. The objective climbed; what slid?

So the loop is recorded as it runs, in the file that renders as its chart.

## The loop

```
       goal from a human or an orchestrator
                    |
                    v
        +---> change ONE thing ----+
        |                          |
        |                          v
        |                   run the verifier
        |                (ngspice, Elmer, FastHenry,
        |                 build123d measure, sch-lint...)
        |                          |
        |                          v
        |                  hw-iterate record
        |                          |
        +--- not there yet <-------+
                    |
              target met, or
              plateaued, or
              out of options
                    |
                    v
            hw-iterate close
            hw-iterate chart  --> the review
```

### 1. Open the loop, and say what "better" means

```bash
hw-iterate open loop-gain \
    --goal "phase margin >= 60 deg without giving up the 1 MHz bandwidth" \
    --objective pm_deg --direction max --target 60 --unit deg \
    --track bw_hz --track-limit bw_hz=1M --track-direction bw_hz=max --track-unit bw_hz=Hz \
    --track iq_ua --track-limit iq_ua=250 --track-direction iq_ua=min --track-unit iq_ua=uA \
    --tool ngspice
```

**`--track` is the important half.** An objective on its own is a licence to
wreck everything else to satisfy it, and a loop that does exactly that looks
like a success from the inside. Name what the objective is not allowed to cost
*before* you start optimising, while you still have no stake in the answer.

If you cannot say what the target is, you do not have a loop — you have an
open question, and that goes to the human now, not after ten iterations.

### 2. One pass, one change, one recorded result

```bash
hw-iterate record loop-gain \
    --var Cc=22p --var Rz=1k5 \
    --metric pm_deg=66 --metric bw_hz=1.35M --metric iq_ua=205 \
    --verdict pass --note "zero in series with Cc buys the margin without the bandwidth" \
    --evidence sim/loop-04.raw
```

* **Every number comes from a run.** `--evidence` names the file it was read
  out of. A metric you reasoned your way to is not a measurement, and
  `hw-iterate status --gate` refuses a loop whose accepted pass has no evidence
  behind it.
* **Record the passes that got worse.** They are the ones that carry
  information — they say which direction is wrong, and they are what stops the
  next session repeating them. A ledger of only wins is a ledger nobody can
  check.
* **Change one thing at a time** where you can. Two knobs at once and the
  ledger cannot tell you which one did it, so neither can anyone else.
* Engineering notation is read as written: `22p`, `1k5`, `4R7`, `1M`.

### 3. Know when to stop

`hw-iterate record` tells you when the last three passes are within 2% of each
other. **That is the signal to change the approach, not to run a fourth
variation of the same idea.** Three tweaks of the same resistor that move the
objective by a tenth of a degree each are not progress; they are a loop
mistaking motion for work.

Stop when any of these is true:

| | Then |
|---|---|
| Target met | `close --status converged --accept N` and go to review |
| Plateaued below target | Change the *approach* — a different topology, a different mechanism. If you have no other approach, escalate with the chart. |
| The objective can only be met by breaching a `--track` limit | **Escalate.** That is a requirements conflict, not an optimisation problem, and it is not yours to resolve. |
| Out of ideas | `close --status escalated`, and say what you tried |

Accept the pass you would actually build, not the highest number. Taking #4
when #6 scored a fraction higher — because #6 needs a part variant nobody
stocks — is a judgement, and the chart shows both so the reviewer sees you made
it.

### 4. Put the trajectory in the review

```bash
hw-iterate chart loop-gain --out docs/design/loop-gain-evolution.svg
review-gate open loop-gain --title "Loop compensation" \
    --summary "60 deg needed a zero, not more Cc. #4 accepted: 66 deg, 1.35 MHz." \
    --artifact docs/design/loop-gain-evolution.svg \
    --question "Take 66 deg at 1.35 MHz, or push for margin and drop below 1 MHz?"
```

The chart shows the objective against its target, each tracked metric against
its own limit, and a strip of which variable moved on which pass. A reviewer
reads three things off it in a second that no paragraph delivers: that it
converged rather than stopped, which change bought the improvement, and what it
cost elsewhere.

## Perseverance and escalation

The two failure modes are symmetric and both are expensive. An agent that stops
at the first obstacle wastes the human's time on things it could have solved.
An agent that never stops burns a day building the wrong thing confidently.

**Push through, without asking, when the problem is in your way:**

* **A tool is missing or broken.** `hw-doctor`, then `hw-repair`. Elmer absent
  is ninety seconds, not a blocker. Konnect's subagents returning nothing is
  `hw-repair konnect`. See `hw-schematic/references/kicad-channels.md` for the
  KiCad failure list.
* **A tool fails on one input.** Read the error, read the log
  (`~/.konnect/logs/calls.jsonl`, `/opt/makehardware/logs/`), try the documented
  alternative. Most of these tools name their replacement in the failure.
* **A solve does not converge, a mesh is bad, a netlist errors.** That is
  ordinary work. `hw-magnetics`, `hw-simulation` and the lint references carry
  the known traps for exactly this reason.
* **The first approach did not work.** Try the second. Three genuinely
  different approaches before you call something hard.
* **You do not know a number that is written down somewhere.** Fetch the
  datasheet. Never ask a human for a figure a document has.

**Stop and ask, before doing the work, when the decision is the human's:**

* **A trade between things they said they wanted.** Margin against bandwidth,
  cost against size, one requirement against another. You cannot rank their
  priorities from the brief, and guessing is how a project builds the wrong
  product correctly.
* **Anything expensive or hard to reverse** — ordering parts, generating fab
  output, committing to a package, a process or a supplier.
* **A number that was agreed, moving.** Re-open the review; do not quietly
  update it.
* **Two readings of the brief lead to different hardware.**
* **The work turns out much bigger than the plan said.** The plan is an
  agreement too.

**The line:** it is a decision if a well-informed human could reasonably
disagree with either answer. It is an obstacle if there is a right answer and
you simply have not found it yet. Obstacles are yours.

**When you do escalate, escalate with work behind it.** Not "the loop did not
converge" but the chart, the three approaches you tried, what each cost, and
the two options you want ranked. An escalation is a decision request with
evidence attached — which is the same standard as any other review, and it is
what makes an interruption worth the human's attention.

**Never fake convergence.** Reporting a target as met when the loop plateaued
below it is the one failure this whole mechanism exists to prevent.
`hw-iterate status --gate` exits 1 on it, and so should you.

## Where the verification comes from

The loop is only as good as the thing closing it. Match the verifier to the
claim:

| The claim | Closed by |
|---|---|
| bias point, gain, margin, noise, transient | `hw-simulation` — ngspice through the spice MCP server |
| L, M, k, Q, R_ac, B field, force | `hw-magnetics` — FastHenry for air-core, Elmer for anything with a core |
| fit, clearance, mass, volume, interference | `hw-cad` — build123d `measure()`, and `compare()` between snapshots |
| thermal rise | Elmer or CalculiX |
| readability, decoupling, DFM | `sch-lint`, `pcb-lint` — they are gates, and a gate is a verifier |
| requirement satisfied | `hw-verification` — the loop's accepted pass is the evidence, cited by path |

A loop whose "verifier" is your own judgement is not a loop. If nothing in the
toolbox can measure the thing, say so — that is a genuine escalation, and a
useful one.
