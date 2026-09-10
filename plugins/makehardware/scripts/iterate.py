#!/usr/bin/env python3
"""The closed design loop, recorded — so a reviewer can check it, not just trust it.

An agent given "get the phase margin above 60 degrees without losing bandwidth"
does not solve it in one pass. It changes a value, simulates, reads the result,
changes something else, and repeats until the objective is met or it runs out
of ideas. That loop is where almost all of the engineering happens, and by
default none of it survives: the repository ends up with the last netlist and a
sentence claiming a number.

That is a bad deal for everyone. The human cannot tell a converged design from
one that stopped when the budget ran out. The next session re-explores knobs
this one already found useless. And nobody can see the trade the loop made —
the objective climbing while something else quietly slid.

So every pass is recorded, in the file that will render as a chart:

    hw-iterate open loop-gain \\
        --goal "phase margin >= 60 deg without giving up bandwidth" \\
        --objective pm_deg --direction max --target 60 --unit deg \\
        --track bw_hz --track-limit bw_hz=1e6 --track-direction bw_hz=max

    hw-iterate record loop-gain \\
        --var Rf=12k --var Cc=4.7p \\
        --metric pm_deg=31 --metric bw_hz=2.1M \\
        --verdict fail --note "datasheet values as the baseline" \\
        --evidence sim/loop-01.raw

    hw-iterate status loop-gain      # where it stands, and whether to stop
    hw-iterate chart  loop-gain      # the SVG a review shows
    hw-iterate close  loop-gain --accept 7 --status converged

The two rules this enforces:

* **Every number comes from a run, not from a belief.** `--evidence` names the
  file the metrics were read out of, and `status` refuses to call a loop
  converged if the accepted iteration has no evidence behind it.
* **The loop reports its trajectory, not just its answer.** `chart` is what
  goes in the review. A single final number is the thing this exists to stop.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

LEDGER_DIR = "docs/design/iterations"

# The plateau test. Three consecutive passes inside this band of each other, on
# the objective, is the signal to stop — not a rule, but the thing the agent
# should have to argue with rather than iterate past without noticing.
PLATEAU_BAND = 0.02
PLATEAU_RUNS = 3

# Decimal exponents, not float multipliers. `22 * 1e-12` is
# 2.1999999999999998e-11 and that is what would land in the ledger and in the
# hover text; `float("22e-12")` is 2.2e-11. The noise is harmless arithmetically
# and corrosive in a file a human reads.
SI = {"T": 12, "G": 9, "M": 6, "k": 3, "K": 3, "": 0,
      "m": -3, "u": -6, "n": -9, "p": -12, "f": -15}

_PLAIN = re.compile(
    r"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*([TGMkKmunpf]?)([a-zA-Z%Ω/]*)$")
# RKM: 1k5, 4R7, 2u2 — the prefix stands in for the decimal point. Ubiquitous
# on schematics and in datasheets, and read as a string it silently becomes a
# variable that never changes, so the "changed" strip on the evolution chart
# shows a knob that moved as a knob that did not.
_RKM = re.compile(r"([+-]?\d+)([RTGMkKmunpf])(\d+)$")


def parse_value(s: str):
    """`12k` -> 12000.0, `4.7p` -> 4.7e-12, `1k5` -> 1500.0, `Device:R` -> itself.

    Engineering notation is how these values are written everywhere else in the
    toolbox, and forcing an agent to expand them by hand is how a factor of a
    thousand gets into a ledger that then charts beautifully and wrongly.
    """
    t = str(s).strip()
    m = _RKM.fullmatch(t)
    if m:
        whole, prefix, frac = m.groups()
        try:
            return float(Decimal(f"{whole}.{frac}").scaleb(
                SI.get("" if prefix == "R" else prefix, 0)))
        except (InvalidOperation, ValueError):
            return t
    m = _PLAIN.fullmatch(t)
    if not m:
        return t
    mant, prefix, _unit = m.groups()
    # Decimal.scaleb, not string concatenation: `1e6` already carries an
    # exponent, and appending another one produces "1e6e0", which is not a
    # number and would silently fall through to the string branch — turning a
    # metric into a label that never plots.
    try:
        return float(Decimal(mant).scaleb(SI.get(prefix, 0)))
    except (InvalidOperation, ValueError):
        return t


def kv(pairs, what):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"hw-iterate: --{what} wants name=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = parse_value(v)
    return out


def path_for(loop: str, directory: str = LEDGER_DIR) -> str:
    return os.path.join(directory, f"{loop}.json")


def load(loop: str, directory: str = LEDGER_DIR) -> dict:
    p = path_for(loop, directory)
    if not os.path.exists(p):
        raise SystemExit(
            f"hw-iterate: no loop {loop!r} at {p}\n"
            f"  open it first:  hw-iterate open {loop} --goal ... --objective ...")
    with open(p) as fh:
        return json.load(fh)


def save(data: dict, directory: str = LEDGER_DIR) -> str:
    p = path_for(data["loop"], directory)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def objective_values(data: dict):
    key = (data.get("objective") or {}).get("metric")
    if not key:
        return key, []
    return key, [(r, num((r.get("metrics") or {}).get(key)))
                 for r in data.get("iterations") or []]


def best_iteration(data: dict):
    key, pairs = objective_values(data)
    have = [(r, v) for r, v in pairs if v is not None]
    if not have:
        return None
    direction = ((data.get("objective") or {}).get("direction") or "max").lower()
    return (max if direction == "max" else min)(have, key=lambda rv: rv[1])


def meets_target(data: dict, value) -> bool | None:
    obj = data.get("objective") or {}
    target = num(obj.get("target"))
    if target is None or value is None:
        return None
    return value >= target if (obj.get("direction") or "max").lower() == "max" \
        else value <= target


def plateaued(data: dict) -> tuple[bool, float | None]:
    _key, pairs = objective_values(data)
    vals = [v for _r, v in pairs if v is not None][-PLATEAU_RUNS:]
    if len(vals) < PLATEAU_RUNS:
        return False, None
    scale = max(abs(v) for v in vals) or 1.0
    span = (max(vals) - min(vals)) / scale
    return span < PLATEAU_BAND, span


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_open(args) -> int:
    p = path_for(args.loop, args.dir)
    if os.path.exists(p) and not args.force:
        raise SystemExit(f"hw-iterate: {p} already exists — use --force to restart it, "
                         f"or `record` to add a pass")
    limits = kv(args.track_limit, "track-limit")
    directions = {k: str(v) for k, v in
                  ((x.split("=", 1) if "=" in x else (x, "max"))
                   for x in (args.track_direction or []))}
    units = {k: str(v) for k, v in
             ((x.split("=", 1) if "=" in x else (x, ""))
              for x in (args.track_unit or []))}
    data = {
        "loop": args.loop,
        "goal": args.goal,
        "opened": date.today().isoformat(),
        "status": "running",
        "objective": {
            "metric": args.objective,
            "direction": args.direction,
            "target": parse_value(args.target) if args.target is not None else None,
            "unit": args.unit or "",
        },
        "track": [{"metric": m,
                   "limit": limits.get(m),
                   "direction": directions.get(m, "max"),
                   "unit": units.get(m, "")}
                  for m in (args.track or [])],
        "tool": args.tool or "",
        "iterations": [],
    }
    print(f"opened {save(data, args.dir)}")
    print(f'  goal      {args.goal}')
    print(f'  objective {args.objective} -> {args.direction}'
          + (f', target {args.target}{(" " + args.unit) if args.unit else ""}'
             if args.target is not None else ' (no target — say when to stop)'))
    if args.track:
        print(f'  watching  {", ".join(args.track)}')
    print("\n  Record every pass, including the ones that got worse. A loop that\n"
          "  only records its wins is a loop nobody can check.")
    return 0


def cmd_record(args) -> int:
    data = load(args.loop, args.dir)
    metrics = kv(args.metric, "metric")
    if not metrics:
        raise SystemExit("hw-iterate: an iteration with no metric is not an "
                         "iteration — what did the run measure?")
    okey = (data.get("objective") or {}).get("metric")
    if okey and okey not in metrics and not args.allow_missing_objective:
        raise SystemExit(
            f"hw-iterate: this loop's objective is {okey!r} and this pass did not "
            f"report it.\n  Either measure it, or pass --allow-missing-objective and "
            f"say in --note why not.")

    rec = {
        "iteration": len(data["iterations"]) + 1,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vars": kv(args.var, "var"),
        "metrics": metrics,
        "verdict": args.verdict,
        "note": args.note or "",
    }
    if args.evidence:
        rec["evidence"] = list(args.evidence)
        missing = [e for e in args.evidence if not os.path.exists(e)]
        if missing:
            print("  WARNING: evidence file(s) do not exist: "
                  + ", ".join(missing), file=sys.stderr)
    data["iterations"].append(rec)
    save(data, args.dir)

    v = num(metrics.get(okey)) if okey else None
    print(f'#{rec["iteration"]} {args.verdict}'
          + (f'  {okey}={metrics[okey]}' if okey in metrics else ""))
    if rec["vars"]:
        print("   changed  " + ", ".join(f"{k}={v_}" for k, v_ in rec["vars"].items()))
    if not rec.get("evidence"):
        print("   no --evidence: this number is unattributable. Name the run "
              "file it came from.")

    hit = meets_target(data, v)
    if hit:
        print(f'\n   Target met. Close the loop: hw-iterate close {args.loop} '
              f'--accept {rec["iteration"]} --status converged')
    flat, span = plateaued(data)
    if flat and not hit:
        print(f"\n   The last {PLATEAU_RUNS} passes are within {span * 100:.1f}% of "
              f"each other and\n   the target is not met. Do not run a fourth "
              f"variation of the same idea:\n   change the approach, or escalate "
              f"with what you have — see hw-optimize.")
    return 0


def cmd_status(args) -> int:
    data = load(args.loop, args.dir)
    its = data.get("iterations") or []
    obj = data.get("objective") or {}
    okey = obj.get("metric")
    unit = obj.get("unit") or ""
    print(f'{data["loop"]} — {data.get("status", "running")}, {len(its)} iterations')
    if data.get("goal"):
        print(f'  goal   {data["goal"]}')
    b = best_iteration(data)
    if b:
        r, v = b
        hit = meets_target(data, v)
        mark = {True: "meets target", False: "SHORT of target",
                None: "no target set"}[hit]
        print(f'  best   #{r["iteration"]}  {okey}={v:g}{(" " + unit) if unit else ""}'
              f'  ({mark})')
    for t in data.get("track") or []:
        k, lim = t.get("metric"), num(t.get("limit"))
        cur = num((its[-1].get("metrics") or {}).get(k)) if its else None
        if cur is None:
            continue
        bad = lim is not None and (
            cur < lim if (t.get("direction") or "max") == "max" else cur > lim)
        print(f'  {k:<8} {cur:g}{(" " + t["unit"]) if t.get("unit") else ""}'
              + (f'   limit {lim:g}{"  BREACHED" if bad else ""}' if lim is not None else ""))
    flat, span = plateaued(data)
    if flat:
        print(f'\n  Plateaued: last {PLATEAU_RUNS} passes within {span * 100:.1f}%.')
    unattributed = [r["iteration"] for r in its if not r.get("evidence")]
    if unattributed:
        print(f'  Unattributed passes (no evidence file): '
              f'{", ".join("#" + str(i) for i in unattributed)}')
    if args.gate:
        problems = []
        if data.get("status") != "converged":
            problems.append(f'status is {data.get("status")!r}, not "converged"')
        acc = next((r for r in its if r.get("accepted")), None)
        if acc is None:
            problems.append("no iteration is marked accepted")
        elif not acc.get("evidence"):
            problems.append(f'accepted iteration #{acc["iteration"]} has no evidence')
        elif meets_target(data, num((acc.get("metrics") or {}).get(okey))) is False:
            problems.append(f'accepted iteration #{acc["iteration"]} does not meet '
                            f'the target')
        if problems:
            print("\n  Loop gate: not clear")
            for p in problems:
                print(f"    - {p}")
            return 1
        print("\n  Loop gate: clear")
    return 0


def cmd_close(args) -> int:
    data = load(args.loop, args.dir)
    its = data.get("iterations") or []
    if args.accept is not None:
        match = [r for r in its if r["iteration"] == args.accept]
        if not match:
            raise SystemExit(f"hw-iterate: no iteration #{args.accept} in this loop")
        for r in its:
            r.pop("accepted", None)
        match[0]["accepted"] = True
    data["status"] = args.status
    if args.note:
        data["closing_note"] = args.note
    data["closed"] = date.today().isoformat()
    save(data, args.dir)
    print(f'{data["loop"]}: {args.status}'
          + (f', accepted #{args.accept}' if args.accept is not None else ""))
    if args.status in ("escalated", "abandoned"):
        print("  Say so in the review request, with what you tried and what you\n"
              "  need decided. A loop that stopped is information, not a failure\n"
              "  to hide.")
    return 0


def cmd_chart(args) -> int:
    data = load(args.loop, args.dir)
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import charts  # noqa: E402  — same directory, no install step
    svg = charts.chart_evolution(data, args.title or f'Design loop — {data["loop"]}',
                                 args.subtitle or "")
    out = args.out or os.path.join(args.dir, f'{data["loop"]}-evolution.svg')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"wrote {out} ({len(svg):,} bytes, {svg.count('<')} elements)")
    print("  Put this on the review page. It is the difference between asking a\n"
          "  reviewer to trust the number and letting them check the search.")
    return 0


def cmd_list(args) -> int:
    if not os.path.isdir(args.dir):
        print(f"no loops (nothing in {args.dir})")
        return 0
    rows = []
    for f in sorted(os.listdir(args.dir)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(args.dir, f)) as fh:
            d = json.load(fh)
        b = best_iteration(d)
        rows.append((d.get("loop", f[:-5]), d.get("status", "?"),
                     len(d.get("iterations") or []),
                     f'{b[1]:g}' if b else "-",
                     {True: "target met", False: "short", None: ""}[
                         meets_target(d, b[1]) if b else None]))
    if not rows:
        print(f"no loops (nothing in {args.dir})")
        return 0
    w = max(len(r[0]) for r in rows)
    for loop, st, n, best, mark in rows:
        print(f"  {loop:<{w}}  {st:<10} {n:>3} passes   best {best:<10} {mark}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="hw-iterate",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=LEDGER_DIR, help="where the ledgers live")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open", help="start a loop and say what it is optimising")
    p.add_argument("loop")
    p.add_argument("--goal", required=True, help="what a human asked for, in their terms")
    p.add_argument("--objective", required=True, metavar="METRIC",
                   help="the metric being driven, e.g. pm_deg")
    p.add_argument("--direction", choices=["max", "min"], default="max")
    p.add_argument("--target", help="the value that ends the loop, e.g. 60 or 1M")
    p.add_argument("--unit", default="", help="unit of the objective, e.g. deg")
    p.add_argument("--track", action="append",
                   help="another metric to watch — what the objective must not cost")
    p.add_argument("--track-limit", action="append", metavar="METRIC=VALUE")
    p.add_argument("--track-direction", action="append", metavar="METRIC=max|min")
    p.add_argument("--track-unit", action="append", metavar="METRIC=UNIT")
    p.add_argument("--tool", help="what verifies a pass, e.g. ngspice, elmer, fasthenry")
    p.add_argument("--force", action="store_true", help="restart an existing loop")
    p.set_defaults(fn=cmd_open)

    p = sub.add_parser("record", help="one verified pass")
    p.add_argument("loop")
    p.add_argument("--var", action="append", metavar="NAME=VALUE",
                   help="what you changed; engineering notation is fine (12k, 4.7p)")
    p.add_argument("--metric", action="append", metavar="NAME=VALUE", required=True,
                   help="what the run measured")
    p.add_argument("--verdict", choices=["pass", "fail", "partial"], required=True)
    p.add_argument("--note", help="one line: what you changed and why")
    p.add_argument("--evidence", action="append",
                   help="the run output the metrics were read from")
    p.add_argument("--allow-missing-objective", action="store_true")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("status", help="where the loop stands, and whether to stop")
    p.add_argument("loop")
    p.add_argument("--gate", action="store_true",
                   help="exit 1 unless the loop converged on an attributed pass")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("close", help="record how the loop ended")
    p.add_argument("loop")
    p.add_argument("--accept", type=int, metavar="N",
                   help="the iteration taken forward")
    p.add_argument("--status", choices=["converged", "escalated", "abandoned"],
                   default="converged")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_close)

    p = sub.add_parser("chart", help="render the evolution SVG for the review")
    p.add_argument("loop")
    p.add_argument("--out")
    p.add_argument("--title", default="")
    p.add_argument("--subtitle", default="")
    p.set_defaults(fn=cmd_chart)

    p = sub.add_parser("list", help="every loop in this project")
    p.set_defaults(fn=cmd_list)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
