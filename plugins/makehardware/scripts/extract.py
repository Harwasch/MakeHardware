#!/usr/bin/env python3
"""Read a number out of a tool's output, so nobody has to retype it.

This exists because of the second rule in this repository's CLAUDE.md:

    Generated, not hand-written. Every number on a review page is read from
    the file that owns it. If you find yourself typing a figure into markdown
    that a tool could compute, that number is already wrong -- it just does
    not know it yet.

The design loop broke that rule from the day it shipped. `hw-iterate record`
took metrics on the command line, so every number on an evolution chart was
one the agent had read off a simulator's output and typed back in. The chart
looked like evidence and was testimony: a transcription, unchecked, of a
number nobody could re-derive. `--evidence` named the file it came from and
nothing ever opened that file.

So: extractors, by name, from the real output formats.

    hw-extract sim/loop-04.log --metric pm_deg=meas:pm --metric bw_hz=meas:bw
    hw-extract solve.log       --metric energy_j="line:ElectroMagnetic Field Energy:"
    hw-extract measure.json    --metric mass_g=json:parts.shell.mass_g
    hw-extract corners.csv     --metric worst_ua=csv:i_standby:max

Every extractor FAILS when its metric is not in the file. That is the whole
point: a loop that silently records nothing for a missing measurement is worse
than one that stops, because the chart still draws and the gap does not show.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


class ExtractError(Exception):
    """A named metric was not in the file. Never a silent None."""


# ---------------------------------------------------------------------------
# extractors
# ---------------------------------------------------------------------------
def x_meas(text: str, name: str) -> float:
    """ngspice's `.meas` / `print` lines.

    Both forms appear in one log and both are accepted:

        fc                  =  9.986000e+02
        fc = 9.986000e+02

    Measured against ngspice 42, not guessed. The last match wins: a deck that
    measures, alters and re-measures leaves both in the log, and the final
    value is the one the run ended on.
    """
    m = re.findall(rf"^\s*{re.escape(name)}\s*=\s*({NUM})", text, re.M)
    if not m:
        # ngspice prints this instead of a value when the condition never
        # occurs, and it is a result, not a parse failure. Say which.
        if re.search(rf"^\s*{re.escape(name)}\s*=\s*failed", text, re.M | re.I):
            raise ExtractError(
                f"ngspice reports measurement {name!r} as failed -- the "
                f"condition it measures never occurred in this run")
        raise ExtractError(f"no measurement named {name!r} in the output")
    return float(m[-1])


def x_line(text: str, prefix: str) -> float:
    """The first number after a literal prefix.

    For solvers that report into a log rather than a file: Elmer's
    `ElectroMagnetic Field Energy:  1.234E-05` is the inductance read-out, and
    the hw-magnetics skill warns it is simply absent below Max Output Level 5.
    """
    m = re.findall(rf"{re.escape(prefix)}\s*:?\s*({NUM})", text)
    if not m:
        raise ExtractError(
            f"no line starting {prefix!r} in the output. For Elmer, check "
            f"`Max Output Level` is 5 -- below that the result line is not "
            f"printed at all and the solve still succeeds")
    return float(m[-1])


def x_re(text: str, pattern: str) -> float:
    """Escape hatch: first capture group of a caller-supplied regex."""
    try:
        rx = re.compile(pattern, re.M)
    except re.error as e:
        raise ExtractError(f"bad regex {pattern!r}: {e}")
    m = rx.search(text)
    if not m:
        raise ExtractError(f"pattern {pattern!r} did not match")
    if not m.groups():
        raise ExtractError(f"pattern {pattern!r} has no capture group to read")
    try:
        return float(m.group(1))
    except ValueError:
        raise ExtractError(f"pattern {pattern!r} captured {m.group(1)!r}, "
                           f"which is not a number")


def x_json(text: str, path: str) -> float:
    """A dotted path into a JSON document. `parts.shell.mass_g`, `rows.0.i`."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractError(f"not JSON: {e}")
    cur = doc
    for i, seg in enumerate(path.split(".")):
        if isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                raise ExtractError(
                    f"{'.'.join(path.split('.')[:i])!r} is a list of "
                    f"{len(cur)}; {seg!r} does not index it")
        elif isinstance(cur, dict):
            if seg not in cur:
                raise ExtractError(
                    f"no key {seg!r} at {'.'.join(path.split('.')[:i]) or '<root>'}"
                    f" -- has {', '.join(sorted(cur)[:8])}")
            cur = cur[seg]
        else:
            raise ExtractError(f"{'.'.join(path.split('.')[:i])!r} is a "
                               f"{type(cur).__name__}, not indexable")
    try:
        return float(cur)
    except (TypeError, ValueError):
        raise ExtractError(f"{path} is {cur!r}, which is not a number")


REDUCERS = {
    "last": lambda v: v[-1], "first": lambda v: v[0],
    "max": max, "min": min,
    "mean": lambda v: sum(v) / len(v),
    "absmax": lambda v: max(v, key=abs),
}


def x_csv(text: str, spec: str) -> float:
    """A column of a CSV, reduced. `i_standby:max`, `vout` (defaults to last).

    The reducer matters more than it looks: a corner sweep's worst case is
    `max`, a settling value is `last`, and taking the wrong one is a number
    that is right about the wrong question.
    """
    parts = spec.split(":")
    column = parts[0]
    how = parts[1] if len(parts) > 1 else "last"
    if how not in REDUCERS:
        raise ExtractError(f"unknown reducer {how!r} -- "
                           f"one of {', '.join(sorted(REDUCERS))}")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ExtractError("no rows in the CSV")
    if column not in rows[0]:
        raise ExtractError(f"no column {column!r} -- "
                           f"has {', '.join(list(rows[0])[:8])}")
    vals = []
    for r in rows:
        raw = (r.get(column) or "").strip()
        if raw in ("", "-", "None", "nan"):
            continue
        try:
            vals.append(float(raw))
        except ValueError:
            continue
    if not vals:
        raise ExtractError(f"column {column!r} holds no numbers")
    return float(REDUCERS[how](vals))


KINDS = {"meas": x_meas, "line": x_line, "re": x_re, "json": x_json,
         "csv": x_csv}


def extract_one(text: str, spec: str) -> float:
    """`meas:pm_deg` -> 66.0. A bare spec is treated as a measurement name."""
    kind, sep, arg = spec.partition(":")
    if not sep:
        kind, arg = "meas", spec
    if kind not in KINDS:
        raise ExtractError(
            f"unknown extractor {kind!r} in {spec!r} -- "
            f"one of {', '.join(sorted(KINDS))}")
    return KINDS[kind](text, arg)


def extract(path: str, metrics: dict[str, str]) -> tuple[dict, dict]:
    """(values, errors) for every requested metric. Never raises on one metric."""
    if not os.path.exists(path):
        return {}, {k: f"{path} does not exist" for k in metrics}
    with open(path, errors="replace") as fh:
        text = fh.read()
    values, errors = {}, {}
    for name, spec in metrics.items():
        try:
            values[name] = extract_one(text, spec)
        except ExtractError as e:
            errors[name] = str(e)
    return values, errors


def parse_metric_args(pairs) -> dict[str, str]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"hw-extract: --metric wants NAME=SPEC, got {p!r}")
        name, spec = p.split("=", 1)
        out[name.strip()] = spec.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="hw-extract",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""extractors:
  meas:NAME        an ngspice `.meas` or `print` line (the default form)
  line:PREFIX      the number after a literal prefix, e.g. an Elmer result line
  re:PATTERN       first capture group of a regex
  json:a.b.0.c     a dotted path into a JSON document
  csv:COL[:how]    a CSV column, reduced by last/first/max/min/mean/absmax
""")
    ap.add_argument("file", help="the tool output to read")
    ap.add_argument("--metric", action="append", metavar="NAME=SPEC",
                    required=True)
    ap.add_argument("--json", action="store_true",
                    help="emit a JSON object instead of NAME=VALUE lines")
    args = ap.parse_args()

    values, errors = extract(args.file, parse_metric_args(args.metric))
    if args.json:
        print(json.dumps({"values": values, "errors": errors}, indent=2))
    else:
        for k, v in values.items():
            print(f"{k}={v:g}")
        for k, e in errors.items():
            print(f"hw-extract: {k}: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
