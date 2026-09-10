#!/usr/bin/env python3
"""The plots a hardware review actually needs, from the file that owns the data.

A hardware review is a set of numbers with a decision attached, and a table of
forty of them is a wall a reviewer skims. The same forty in the right picture
answer the question in a second: *which rail is closest to its limit*, *which
corner fails*, *how much phase margin is left*. That is the whole job.

Every chart here is built to one set of rules, and the rules are the point:

* **Direct labelling, never a legend.** A legend makes the reader hold a
  colour in their head and walk back and forth. Put the name at the end of the
  line.
* **Show the limit, and show the distance to it.** A bar chart of current draw
  says nothing; the same bars against their budget say everything.
* **Annotate the anomaly.** The failing corner gets the callout. If nothing is
  annotated, the reader has to find the story themselves, and they will not.
* **No chartjunk.** No 3D, no gradient fills, no gridlines the eye trips over,
  no frame. Ink that is not data is ink working against data.
* **Small multiples share a scale.** Six panels with six y-axes is six charts;
  six panels on one scale is a comparison.
* **State is never colour alone.** A failing bar is red *and* carries its
  number and a marker, so it survives a mono print and a colour-blind reader.

Output is SVG: it inlines on the review page, renders on github.com, stays
crisp at any zoom, follows the reader's light/dark theme, and has no byte
budget worth worrying about. Every value also lands in a `<title>`, so the
number is one hover away.

Usage:
    hw-chart budget    rails.csv     --out docs/design/power-budget.svg
    hw-chart corners   corners.csv   --out docs/design/standby-corners.svg
    hw-chart bode      ac.csv        --out docs/design/loop-gain.svg
    hw-chart trace     tran.csv      --out docs/design/startup.svg
    hw-chart coverage  coverage.json --out docs/design/coverage.svg
    hw-chart waterfall bom.csv       --out docs/design/cost.svg
    hw-chart stackup   stackup.json  --out docs/design/stackup.svg
    hw-chart evolution loop.json     --out docs/design/loop-evolution.svg

Run `hw-chart <kind> --schema` to see exactly what columns each one wants.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

# The palette the rest of the toolbox already draws with, so a review page does
# not look like six different documents. See block_diagram.py / req_trace.py.
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
CARD = {"light": "#ffffff", "dark": "#242422"}
INK = {"light": "#0b0b0b", "dark": "#ffffff"}
INK2 = {"light": "#52514e", "dark": "#c3c2b7"}
MUTED = "#898781"
AXIS = {"light": "#c3c2b7", "dark": "#383835"}
FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")

FAIL = "#d03b3b"     # the same red req_trace uses for a gap
WARN = "#e08a1e"
PASS = "#2e8b57"
SERIES = ["#4b7fae", "#c06a2e", "#4f9d69", "#8b5fa8", "#b8983a", "#5c7a8a"]

W = 760              # a comfortable width inside the review page's column


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _trim(x: float) -> str:
    s = f"{x:.0f}" if abs(x) >= 100 else (f"{x:.1f}" if abs(x) >= 10
                                          else f"{x:.3g}")
    return s.rstrip("0").rstrip(".") if "." in s else s


def si(v: float, unit: str = "", scale: bool = None) -> str:
    """A number a person reads, not a float a computer prints.

    SI prefixing is applied only when the caller has not already told us the
    unit. `41.7` with `unit="uA"` is 41.7 uA and must print as such — rescaling
    it produces "41.7uuA", and rescaling `0.47` with `unit="C"` produces
    "470mC", which is a temperature nobody has ever written down. Computed
    quantities (a crossover frequency in Hz) pass `scale=True` and do get
    prefixed.
    """
    if v is None:
        return "-"
    if scale is None:
        scale = not unit
    if not scale:
        return f"{_trim(v)}{(' ' + unit) if unit else ''}"
    if v == 0:
        return f"0{unit}"
    a = abs(v)
    for step, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""),
                         (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if a >= step or step == 1e-12:
            return f"{_trim(v / step)}{suffix}{unit}"
    return f"{v}{unit}"


def head(width: int, height: int, title: str = "", subtitle: str = "") -> list[str]:
    """The document shell: theme-aware, no frame, no chartjunk."""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
         f'height="{height}" viewBox="0 0 {width} {height}" '
         f'font-family="{FONT}" role="img">',
         "<style>"
         f".s{{fill:{SURFACE['light']}}} .ink{{fill:{INK['light']}}} "
         f".ink2{{fill:{INK2['light']}}} .ax{{stroke:{AXIS['light']}}} "
         f".axf{{fill:{AXIS['light']}}} .card{{fill:{CARD['light']}}}"
         "@media (prefers-color-scheme:dark){"
         f".s{{fill:{SURFACE['dark']}}} .ink{{fill:{INK['dark']}}} "
         f".ink2{{fill:{INK2['dark']}}} .ax{{stroke:{AXIS['dark']}}} "
         f".axf{{fill:{AXIS['dark']}}} .card{{fill:{CARD['dark']}}}}}"
         "</style>",
         f'<rect class="s" width="{width}" height="{height}"/>']
    if title:
        o.append(f'<text class="ink" x="16" y="26" font-size="16" '
                 f'font-weight="600">{esc(title)}</text>')
    if subtitle:
        o.append(f'<text class="ink2" x="16" y="45" font-size="12">'
                 f'{esc(subtitle)}</text>')
    return o


def read_rows(path: str) -> list[dict]:
    if path.endswith(".jsonl") or path.endswith(".ndjson"):
        return read_jsonl(path)
    if path.endswith(".json"):
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else data.get("rows", [])
    with open(path, newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def read_jsonl(path: str) -> list[dict]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def read_object(path: str):
    """The whole file, for a chart whose data is a document rather than rows.

    `evolution` needs the ledger's objective and limits, not just its
    iterations — reading it as rows throws away the very thing that turns a
    line into a judgement.
    """
    if path.endswith(".jsonl") or path.endswith(".ndjson"):
        return read_jsonl(path)
    if path.endswith(".json"):
        with open(path) as fh:
            return json.load(fh)
    return read_rows(path)


def num(row, *keys, default=None):
    for k in keys:
        if k in row and str(row[k]).strip() not in ("", "-", "None"):
            try:
                return float(str(row[k]).strip().replace(",", ""))
            except ValueError:
                continue
    return default


def text(row, *keys, default=""):
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return default


# --------------------------------------------------------------------------
# budget — the chart the architecture review is actually about
# --------------------------------------------------------------------------
BUDGET_SCHEMA = """\
budget — one row per rail or per consumer.

  name,used,budget,unit
  3V3,38.2,40,mA
  3V3_ANA,4.1,12,mA
  5V_USB,110,500,mA

`unit` is optional and may differ per row. Anything at or over budget is drawn
red with its overage called out; the closest-to-limit row is annotated whether
or not it fails, because that is the row the review is about."""


def chart_budget(rows, title, subtitle) -> str:
    items = []
    for r in rows:
        used = num(r, "used", "actual", "measured", "value", default=0.0) or 0.0
        cap = num(r, "budget", "limit", "max", "capacity")
        items.append({"name": text(r, "name", "rail", "id", default="?"),
                      "used": used, "cap": cap,
                      "unit": text(r, "unit", default="")})
    if not items:
        return "".join(head(W, 80, title or "Budget", "no rows"))+"</svg>"

    lab_w = 118
    bar_x = 16 + lab_w
    bar_w = W - bar_x - 190
    row_h, gap = 26, 10
    top = 62 if (title or subtitle) else 20
    height = top + len(items) * (row_h + gap) + 34

    o = head(W, height, title or "Budget against limit", subtitle)
    worst = max(items, key=lambda it: (it["used"] / it["cap"]) if it["cap"] else 0)

    y = top
    for it in items:
        cap = it["cap"]
        frac = (it["used"] / cap) if cap else 0.0
        over = cap is not None and it["used"] > cap
        col = FAIL if over else (WARN if frac > 0.85 else PASS)
        o.append(f'<text class="ink" x="16" y="{y + 17}" font-size="12.5" '
                 f'text-anchor="start">{esc(it["name"])}</text>')
        # The budget track: the thing the bar is measured against, drawn first
        # and quietly, so the bar reads as a fraction of it rather than as a
        # length on its own.
        o.append(f'<rect class="card" x="{bar_x}" y="{y}" width="{bar_w}" '
                 f'height="{row_h}" rx="3"/>'
                 f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{row_h}" '
                 f'rx="3" fill="none" class="ax" stroke-width="1"/>')
        w = max(2.0, min(1.0, frac) * bar_w) if cap else bar_w * 0.5
        o.append(f'<rect x="{bar_x}" y="{y}" width="{w:.1f}" height="{row_h}" '
                 f'rx="3" fill="{col}" fill-opacity=".85">'
                 f'<title>{esc(it["name"])}: {si(it["used"], it["unit"])} of '
                 f'{si(cap, it["unit"]) if cap else "no budget"}'
                 f'{f" ({100 * frac:.0f}%)" if cap else ""}</title></rect>')
        if over:
            o.append(f'<rect x="{bar_x + bar_w}" y="{y + 5}" '
                     f'width="{min(24, (frac - 1) * bar_w):.1f}" '
                     f'height="{row_h - 10}" fill="{FAIL}"/>')
        val = si(it["used"], it["unit"])
        cap_s = f" / {si(cap, it['unit'])}" if cap else ""
        pct = f"  {100 * frac:.0f}%" if cap else ""
        o.append(f'<text class="ink" x="{bar_x + bar_w + 12}" y="{y + 17}" '
                 f'font-size="12.5" fill="{col if (over or frac > 0.85) else None}">'
                 f'{esc(val + cap_s)}</text>')
        o.append(f'<text class="ink2" x="{bar_x + bar_w + 12}" y="{y + 17}" '
                 f'font-size="12.5" opacity="0">{esc(pct)}</text>')
        if it is worst and cap:
            o.append(f'<text x="{bar_x + bar_w + 12}" y="{y + 17 + 13}" '
                     f'font-size="10.5" fill="{col}">'
                     f'{"OVER by " + si(it["used"] - cap, it["unit"]) if over else f"{100 * frac:.0f}% of budget"}'
                     f'</text>')
        y += row_h + gap

    o.append(f'<text class="axf" x="16" y="{height - 12}" font-size="10.5">'
             f'bar = drawn, outline = budget. '
             f'Worst: {esc(worst["name"])}</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# corners — small multiples, one scale, the failure annotated
# --------------------------------------------------------------------------
CORNERS_SCHEMA = """\
corners — one row per corner of one measurement, or per (measurement, corner).

  measurement,corner,value,spec,direction,unit
  Iq standby,25C 3.3V,38.2,40,max,uA
  Iq standby,85C 3.0V,41.7,40,max,uA
  Iq standby,-20C 3.6V,31.0,40,max,uA

`direction` is `max` (value must not exceed spec) or `min`. Panels share one
scale per measurement so the corners can be compared by eye, which is the only
reason to draw them together."""


def chart_corners(rows, title, subtitle) -> str:
    groups: dict = {}
    for r in rows:
        m = text(r, "measurement", "name", "metric", default="value")
        groups.setdefault(m, []).append({
            "corner": text(r, "corner", "case", "condition", default="?"),
            "value": num(r, "value", "measured", "result", default=0.0) or 0.0,
            "spec": num(r, "spec", "limit", "requirement", "budget"),
            "dir": text(r, "direction", "sense", default="max").lower(),
            "unit": text(r, "unit", default=""),
        })
    if not groups:
        return "".join(head(W, 80, title or "Corners", "no rows")) + "</svg>"

    cols = min(3, len(groups)) if len(groups) > 1 else 1
    panel_w = (W - 32 - 16 * (cols - 1)) / cols
    rows_n = math.ceil(len(groups) / cols)
    panel_h = 150
    top = 62 if (title or subtitle) else 20
    height = int(top + rows_n * (panel_h + 30) + 20)

    o = head(W, height, title or "Corner results against spec", subtitle)
    for i, (name, items) in enumerate(groups.items()):
        cx = 16 + (i % cols) * (panel_w + 16)
        cy = top + (i // cols) * (panel_h + 30)
        vals = [it["value"] for it in items]
        specs = [it["spec"] for it in items if it["spec"] is not None]
        lo = min(vals + specs + [0.0])
        hi = max(vals + specs)
        span = (hi - lo) or 1.0
        lo -= 0.08 * span
        hi += 0.12 * span
        span = hi - lo

        def yy(v):
            return cy + panel_h - (v - lo) / span * (panel_h - 24)

        o.append(f'<text class="ink" x="{cx}" y="{cy - 6}" font-size="12.5" '
                 f'font-weight="600">{esc(name)}</text>')
        o.append(f'<line class="ax" x1="{cx}" y1="{cy + panel_h}" '
                 f'x2="{cx + panel_w}" y2="{cy + panel_h}" stroke-width="1"/>')

        if specs:
            sy = yy(specs[0])
            o.append(f'<line x1="{cx}" y1="{sy:.1f}" x2="{cx + panel_w}" '
                     f'y2="{sy:.1f}" stroke="{FAIL}" stroke-width="1.2" '
                     f'stroke-dasharray="4 3" opacity=".8"/>')
            o.append(f'<text x="{cx + panel_w}" y="{sy - 4:.1f}" '
                     f'text-anchor="end" font-size="10" fill="{FAIL}">'
                     f'spec {si(specs[0], items[0]["unit"])}</text>')

        n = len(items)
        bw = (panel_w - 12) / max(n, 1) * 0.55
        for k, it in enumerate(items):
            x = cx + 6 + (k + 0.5) * (panel_w - 12) / n
            spec = it["spec"]
            bad = spec is not None and (
                it["value"] > spec if it["dir"] != "min" else it["value"] < spec)
            col = FAIL if bad else PASS
            y0, y1 = yy(it["value"]), cy + panel_h
            against = (f" against {si(spec, it['unit'])}"
                       if spec is not None else "")
            emphasis = f'fill="{FAIL}" font-weight="600"' if bad else ""
            o.append(f'<rect x="{x - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}" '
                     f'height="{max(1.0, y1 - y0):.1f}" fill="{col}" '
                     f'fill-opacity="{0.9 if bad else 0.65}">'
                     f'<title>{esc(it["corner"])}: '
                     f'{si(it["value"], it["unit"])}{esc(against)}'
                     f'</title></rect>')
            o.append(f'<text class="ink" x="{x:.1f}" y="{y0 - 5:.1f}" '
                     f'text-anchor="middle" font-size="10" {emphasis}>'
                     f'{esc(si(it["value"], it["unit"]))}</text>')
            o.append(f'<text class="axf" x="{x:.1f}" y="{cy + panel_h + 13:.1f}" '
                     f'text-anchor="middle" font-size="9.5">'
                     f'{esc(it["corner"][:16])}</text>')
            if bad:
                # The failure is the story. Mark it with a shape as well as a
                # colour, so it survives a mono print and a colour-blind reader.
                o.append(f'<text x="{x:.1f}" y="{y0 - 17:.1f}" '
                         f'text-anchor="middle" font-size="11" fill="{FAIL}" '
                         f'font-weight="700">x</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# trace / bode — xy with the measurement called out
# --------------------------------------------------------------------------
TRACE_SCHEMA = """\
trace — an xy plot. First column is x; every other numeric column is a series,
labelled at the end of its own line rather than in a legend.

  t,vout,vin
  0,0,0
  1e-6,0.4,3.3

Optional flags: --xlabel, --ylabel, --logx, --mark "x=1e-3,label=turn-on"."""

BODE_SCHEMA = """\
bode — gain and phase against frequency, with the margins measured and marked.

  freq,gain_db,phase_deg
  10,52.1,-92
  1000,21.0,-118

Gain and phase crossings, phase margin and gain margin are computed from the
data and annotated; nothing is typed in."""


def _series(rows):
    if not rows:
        return "", [], {}
    cols = list(rows[0].keys())
    xk = cols[0]
    xs, series = [], {}
    for c in cols[1:]:
        series[c] = []
    for r in rows:
        try:
            xs.append(float(str(r[xk]).strip()))
        except (ValueError, KeyError):
            continue
        for c in cols[1:]:
            series[c].append(num(r, c))
    return xk, xs, {k: v for k, v in series.items() if any(x is not None for x in v)}


def _nice(lo: float, hi: float, n: int = 4) -> list[float]:
    """Round tick values inside [lo, hi].

    An axis reading 59 / 8.02 / -43 is an axis whose numbers came from the
    data's own extremes. Nobody reads those; they read 50 / 0 / -50.
    """
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(n - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10)),
               key=lambda s: abs(s - raw))
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out or [lo, hi]


def _axes(o, x0, y0, w, h, xs, ys, logx=False, xlabel="", ylabel=""):
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    if logx:
        lo_x = max(lo_x, 1e-12)
        lx0, lx1 = math.log10(lo_x), math.log10(max(hi_x, lo_x * 10))
    pad = (hi_y - lo_y) * 0.08 or 1.0
    lo_y -= pad
    hi_y += pad

    def X(v):
        if logx:
            v = max(v, 1e-12)
            return x0 + (math.log10(v) - lx0) / max(lx1 - lx0, 1e-9) * w
        return x0 + (v - lo_x) / max(hi_x - lo_x, 1e-9) * w

    def Y(v):
        return y0 + h - (v - lo_y) / max(hi_y - lo_y, 1e-9) * h

    o.append(f'<line class="ax" x1="{x0}" y1="{y0 + h}" x2="{x0 + w}" '
             f'y2="{y0 + h}" stroke-width="1"/>')
    o.append(f'<line class="ax" x1="{x0}" y1="{y0}" x2="{x0}" '
             f'y2="{y0 + h}" stroke-width="1"/>')
    # A few round ticks a side. More than that is a grid, and a grid is ink
    # competing with the data for the reader's attention.
    for v in _nice(lo_y, hi_y, 4):
        o.append(f'<text class="axf" x="{x0 - 6}" y="{Y(v) + 3.5:.1f}" '
                 f'text-anchor="end" font-size="10">'
                 f'{esc(si(v, scale=True))}</text>')
    if logx:
        d0, d1 = math.ceil(lx0), math.floor(lx1)
        decades = list(range(int(d0), int(d1) + 1))
        stride = max(1, len(decades) // 5)
        for d in decades[::stride]:
            v = 10 ** d
            o.append(f'<text class="axf" x="{X(v):.1f}" y="{y0 + h + 14}" '
                     f'text-anchor="middle" font-size="10">'
                     f'{esc(si(v, scale=True))}</text>')
    else:
        for v in _nice(lo_x, hi_x, 4):
            o.append(f'<text class="axf" x="{X(v):.1f}" y="{y0 + h + 14}" '
                     f'text-anchor="middle" font-size="10">'
                     f'{esc(si(v, scale=True))}</text>')
    if xlabel:
        o.append(f'<text class="axf" x="{x0 + w}" y="{y0 + h + 28}" '
                 f'text-anchor="end" font-size="10.5">{esc(xlabel)}</text>')
    if ylabel:
        o.append(f'<text class="axf" x="{x0}" y="{y0 - 8}" font-size="10.5">'
                 f'{esc(ylabel)}</text>')
    return X, Y


def chart_trace(rows, title, subtitle, cfg) -> str:
    xk, xs, series = _series(rows)
    if not xs or not series:
        return "".join(head(W, 80, title or "Trace", "no numeric data")) + "</svg>"
    top = 62 if (title or subtitle) else 24
    h = 260
    height = top + h + 46
    o = head(W, height, title or "", subtitle)
    x0, y0, w = 52, top, W - 52 - 110
    allys = [v for vs in series.values() for v in vs if v is not None]
    X, Y = _axes(o, x0, y0, w, h, xs, allys, logx=cfg.logx,
                 xlabel=cfg.xlabel or xk, ylabel=cfg.ylabel)

    for i, (name, vs) in enumerate(series.items()):
        col = SERIES[i % len(SERIES)]
        pts, last = [], None
        for x, v in zip(xs, vs):
            if v is None:
                continue
            pts.append(f"{X(x):.1f},{Y(v):.1f}")
            last = (X(x), Y(v))
        o.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                 f'stroke="{col}" stroke-width="1.8" stroke-linejoin="round">'
                 f'<title>{esc(name)}</title></polyline>')
        if last:
            # Direct labelling. A legend makes the reader hold a colour in
            # their head and walk back and forth; the name at the end of the
            # line does not.
            o.append(f'<text x="{last[0] + 6:.1f}" y="{last[1] + 4:.1f}" '
                     f'font-size="11.5" fill="{col}">{esc(name)}</text>')

    for m in cfg.mark or []:
        parts = dict(kv.split("=", 1) for kv in m.split(",") if "=" in kv)
        try:
            mx = float(parts.get("x", "nan"))
        except ValueError:
            continue
        o.append(f'<line x1="{X(mx):.1f}" y1="{y0}" x2="{X(mx):.1f}" '
                 f'y2="{y0 + h}" stroke="{WARN}" stroke-width="1" '
                 f'stroke-dasharray="3 3"/>')
        o.append(f'<text x="{X(mx) + 4:.1f}" y="{y0 + 12}" font-size="10.5" '
                 f'fill="{WARN}">{esc(parts.get("label", si(mx)))}</text>')
    o.append("</svg>")
    return "\n".join(o)


def chart_bode(rows, title, subtitle, cfg) -> str:
    freq = [num(r, "freq", "frequency", "f", "hz") for r in rows]
    gain = [num(r, "gain_db", "gain", "mag_db", "db") for r in rows]
    phase = [num(r, "phase_deg", "phase", "deg") for r in rows]
    pts = [(f, g, p) for f, g, p in zip(freq, gain, phase)
           if f is not None and g is not None]
    if not pts:
        return "".join(head(W, 80, title or "Bode", "no data")) + "</svg>"

    # Crossings are computed, never typed. A margin someone typed into a
    # caption is a margin that stopped being true at the next simulation.
    fc = pm = gm = None
    for (f1, g1, p1), (f2, g2, p2) in zip(pts, pts[1:]):
        if g1 > 0 >= g2 and fc is None:
            t = g1 / (g1 - g2) if g1 != g2 else 0
            fc = f1 + t * (f2 - f1)
            if p1 is not None and p2 is not None:
                pm = 180 + (p1 + t * (p2 - p1))
        if p1 is not None and p2 is not None and p1 > -180 >= p2 and gm is None:
            t = (p1 + 180) / (p1 - p2) if p1 != p2 else 0
            gm = -(g1 + t * (g2 - g1))

    top = 62 if (title or subtitle) else 24
    h1, h2 = 170, 120
    height = top + h1 + 34 + h2 + 48
    sub = subtitle
    if fc is not None:
        sub = (sub + "   " if sub else "") + f"crossover {si(fc, 'Hz', scale=True)}"
        if pm is not None:
            sub += f",  phase margin {pm:.0f} deg"
        if gm is not None:
            sub += f",  gain margin {gm:.1f} dB"
    o = head(W, height, title or "Loop gain", sub)

    x0, w = 52, W - 52 - 60
    fs = [p[0] for p in pts]
    X, Y = _axes(o, x0, top, w, h1, fs, [p[1] for p in pts], logx=True,
                 ylabel="gain (dB)")
    o.append('<polyline points="' +
             " ".join(f"{X(f):.1f},{Y(g):.1f}" for f, g, _ in pts) +
             f'" fill="none" stroke="{SERIES[0]}" stroke-width="1.8"/>')
    o.append(f'<line x1="{x0}" y1="{Y(0):.1f}" x2="{x0 + w}" y2="{Y(0):.1f}" '
             f'stroke="{MUTED}" stroke-width="1" stroke-dasharray="3 3"/>')

    y2 = top + h1 + 34
    ph = [(f, p) for f, _, p in pts if p is not None]
    if ph:
        Xp, Yp = _axes(o, x0, y2, w, h2, [p[0] for p in ph],
                       [p[1] for p in ph], logx=True, xlabel="frequency (Hz)",
                       ylabel="phase (deg)")
        o.append('<polyline points="' +
                 " ".join(f"{Xp(f):.1f},{Yp(p):.1f}" for f, p in ph) +
                 f'" fill="none" stroke="{SERIES[1]}" stroke-width="1.8"/>')
        o.append(f'<line x1="{x0}" y1="{Yp(-180):.1f}" x2="{x0 + w}" '
                 f'y2="{Yp(-180):.1f}" stroke="{FAIL}" stroke-width="1" '
                 f'stroke-dasharray="4 3" opacity=".7"/>')
        o.append(f'<text x="{x0 + w}" y="{Yp(-180) - 4:.1f}" text-anchor="end" '
                 f'font-size="10" fill="{FAIL}">-180</text>')

    if fc is not None:
        col = FAIL if (pm is not None and pm < 45) else PASS
        o.append(f'<line x1="{X(fc):.1f}" y1="{top}" x2="{X(fc):.1f}" '
                 f'y2="{y2 + h2}" stroke="{col}" stroke-width="1" '
                 f'stroke-dasharray="2 3" opacity=".8"/>')
        o.append(f'<circle cx="{X(fc):.1f}" cy="{Y(0):.1f}" r="4" fill="none" '
                 f'stroke="{col}" stroke-width="1.6"/>')
        if pm is not None:
            o.append(f'<text x="{X(fc) + 6:.1f}" y="{y2 + 16}" font-size="11" '
                     f'fill="{col}" font-weight="600">PM {pm:.0f} deg'
                     f'{" — thin" if pm < 45 else ""}</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# coverage — requirements, honestly
# --------------------------------------------------------------------------
COVERAGE_SCHEMA = """\
coverage — one row per level or per group.

  level,verified,partial,unverified
  System,12,3,5
  Electrical,22,1,9

Or the JSON `req-trace --json` already emits. Gaps are drawn first and named,
because "lead with gaps, not percentages" is the house rule."""


def chart_coverage(rows, title, subtitle) -> str:
    items = []
    for r in rows:
        items.append({
            "name": text(r, "level", "group", "name", default="?"),
            "ver": num(r, "verified", "ok", default=0) or 0,
            "part": num(r, "partial", "in_progress", default=0) or 0,
            "un": num(r, "unverified", "gaps", "missing", default=0) or 0,
        })
    if not items:
        return "".join(head(W, 80, title or "Coverage", "no rows")) + "</svg>"
    tot_un = sum(it["un"] for it in items)
    tot = sum(it["ver"] + it["part"] + it["un"] for it in items)
    sub = subtitle or (f"{int(tot_un)} of {int(tot)} requirements have no "
                       f"evidence" if tot else "")

    lab_w = 130
    bar_x = 16 + lab_w
    bar_w = W - bar_x - 140
    row_h, gap = 24, 10
    top = 62
    height = top + len(items) * (row_h + gap) + 30
    o = head(W, height, title or "Requirement coverage", sub)
    widest = max(it["ver"] + it["part"] + it["un"] for it in items) or 1

    y = top
    for it in items:
        n = it["ver"] + it["part"] + it["un"]
        scale = bar_w / widest
        o.append(f'<text class="ink" x="16" y="{y + 16}" font-size="12.5">'
                 f'{esc(it["name"])}</text>')
        x = bar_x
        for val, col, lab in ((it["un"], FAIL, "no evidence"),
                              (it["part"], WARN, "partial"),
                              (it["ver"], PASS, "verified")):
            if val <= 0:
                continue
            w = val * scale
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" '
                     f'height="{row_h}" fill="{col}" fill-opacity=".85">'
                     f'<title>{esc(it["name"])}: {int(val)} {lab}</title></rect>')
            if w > 22:
                o.append(f'<text x="{x + w / 2:.1f}" y="{y + 16}" '
                         f'text-anchor="middle" font-size="11" fill="#fff">'
                         f'{int(val)}</text>')
            x += w
        o.append(f'<text class="ink2" x="{bar_x + bar_w + 12}" y="{y + 16}" '
                 f'font-size="11.5">{int(it["ver"])}/{int(n)} verified</text>')
        y += row_h + gap
    o.append(f'<text class="axf" x="16" y="{height - 10}" font-size="10.5">'
             f'gaps first, then partial, then verified</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# waterfall — where the budget went
# --------------------------------------------------------------------------
WATERFALL_SCHEMA = """\
waterfall — a total broken into contributions, biggest first.

  name,value,unit
  MCU,1.82,GBP
  Display,4.10,GBP
  Enclosure,3.55,GBP

Use it for BOM cost, for a power budget by consumer, or for a mass budget. The
running total is drawn as it accumulates, so the reader sees which two items
are the whole story."""


def chart_waterfall(rows, title, subtitle) -> str:
    items = [{"name": text(r, "name", "item", "id", default="?"),
              "value": num(r, "value", "cost", "current", "mass", default=0.0) or 0.0,
              "unit": text(r, "unit", default="")}
             for r in rows]
    items.sort(key=lambda it: -abs(it["value"]))
    if not items:
        return "".join(head(W, 80, title or "Waterfall", "no rows")) + "</svg>"
    total = sum(it["value"] for it in items)
    unit = items[0]["unit"]
    top = 62
    bar_w = W - 300
    row_h, gap = 22, 8
    height = top + (len(items) + 1) * (row_h + gap) + 26
    o = head(W, height, title or "Where it goes",
             subtitle or f"total {si(total, unit)} across {len(items)} items")

    run = 0.0
    y = top
    for i, it in enumerate(items):
        frac0 = run / total if total else 0
        run += it["value"]
        frac1 = run / total if total else 0
        col = SERIES[i % len(SERIES)]
        o.append(f'<text class="ink" x="16" y="{y + 15}" font-size="12">'
                 f'{esc(it["name"])}</text>')
        x = 150 + frac0 * bar_w
        w = max(1.5, (frac1 - frac0) * bar_w)
        o.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{row_h}" '
                 f'fill="{col}" fill-opacity=".85" rx="2">'
                 f'<title>{esc(it["name"])}: {si(it["value"], it["unit"] or unit)} '
                 f'({100 * (frac1 - frac0):.0f}%)</title></rect>')
        o.append(f'<text class="ink2" x="{150 + bar_w + 10}" y="{y + 15}" '
                 f'font-size="11.5">{esc(si(it["value"], it["unit"] or unit))}'
                 f'   {100 * (frac1 - frac0):.0f}%</text>')
        y += row_h + gap
    o.append(f'<line class="ax" x1="150" y1="{y - 2}" x2="{150 + bar_w}" '
             f'y2="{y - 2}" stroke-width="1"/>')
    o.append(f'<text class="ink" x="16" y="{y + 16}" font-size="12.5" '
             f'font-weight="600">Total</text>')
    o.append(f'<text class="ink" x="{150 + bar_w + 10}" y="{y + 16}" '
             f'font-size="12.5" font-weight="600">{esc(si(total, unit))}</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# stackup — the cross-section a layout review needs
# --------------------------------------------------------------------------
STACKUP_SCHEMA = """\
stackup — the layer cross-section, top to bottom.

  name,type,thickness_um,reference
  F.Cu,signal,35,In1.Cu
  dielectric 1,prepreg,200,
  In1.Cu,plane,35,

`type` is signal, plane, power, prepreg or core. A signal layer whose
`reference` is empty is drawn with the warning, because a signal layer with no
reference plane has no return path."""


def chart_stackup(rows, title, subtitle) -> str:
    items = [{"name": text(r, "name", "layer", default="?"),
              "type": text(r, "type", "kind", default="signal").lower(),
              "t": num(r, "thickness_um", "thickness", "um", default=35.0) or 35.0,
              "ref": text(r, "reference", "ref", default="")}
             for r in rows]
    if not items:
        return "".join(head(W, 80, title or "Stackup", "no rows")) + "</svg>"
    top = 62
    total_t = sum(it["t"] for it in items) or 1.0
    draw_h = 300
    x0, w = 150, 300
    # Thicknesses span two orders of magnitude — 35 um of copper against 1.1 mm
    # of core — so a true-scale cross-section is a picture of the core with
    # hairlines on it. A power-law compression keeps the ordering visible
    # without flattening it to nothing the way a log does, and the real
    # micrometre figure is printed beside every layer anyway.
    weights = [max(it["t"], 1.0) ** 0.35 for it in items]
    tot_w = sum(weights) or 1.0
    heights = [max(13.0, draw_h * wgt / tot_w) for wgt in weights]
    height = int(top + sum(heights) + 2 * len(items) + 26)
    coppers = sum(1 for it in items
                  if it["type"] in ("signal", "plane", "power", "mixed"))
    o = head(W, height, title or "Layer stackup",
             subtitle or f"{coppers} copper layers, {total_t / 1000:.2f} mm overall")

    y = top
    for it, h in zip(items, heights):
        kind = it["type"]
        if kind in ("plane", "power", "gnd", "ground"):
            fill, label = "#b48b3f", "plane"
        elif kind in ("signal",):
            fill, label = "#c98a4b", "signal"
        else:
            fill, label = "#7f8c95", kind
        o.append(f'<rect x="{x0}" y="{y:.1f}" width="{w}" height="{h:.1f}" '
                 f'fill="{fill}" fill-opacity=".8">'
                 f'<title>{esc(it["name"])}: {it["t"]:.0f} um {esc(kind)}</title>'
                 f'</rect>')
        o.append(f'<text class="ink" x="{x0 - 10}" y="{y + h / 2 + 4:.1f}" '
                 f'text-anchor="end" font-size="12">{esc(it["name"])}</text>')
        o.append(f'<text class="ink2" x="{x0 + w + 12}" y="{y + h / 2 + 4:.1f}" '
                 f'font-size="11">{it["t"]:.0f} um  {esc(label)}</text>')
        if kind == "signal":
            if it["ref"]:
                o.append(f'<text class="ink2" x="{x0 + w + 118}" '
                         f'y="{y + h / 2 + 4:.1f}" font-size="11" fill="{PASS}">'
                         f'ref {esc(it["ref"])}</text>')
            else:
                o.append(f'<text x="{x0 + w + 118}" y="{y + h / 2 + 4:.1f}" '
                         f'font-size="11" fill="{FAIL}" font-weight="600">'
                         f'x no ref plane</text>')
        y += h + 2
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# evolution — the design loop, not the design
#
# Every other chart here shows where a design ended up. This one shows how it
# got there, which is a different and often more useful thing to put in front
# of a reviewer: whether the objective is still improving or has plateaued,
# which change bought the improvement, and what it cost somewhere else.
#
# A closed-loop run that reports only its final number is asking to be trusted.
# The same run with its trajectory drawn is asking to be *checked* — a reviewer
# can see three iterations of noise around one value and say "that is converged,
# stop", or see a metric quietly sliding while the objective climbs and say
# "you are trading away the thing I care about".
# --------------------------------------------------------------------------
EVOLUTION_SCHEMA = """\
evolution — the iteration ledger `hw-iterate` writes. Normally you never build
this by hand:

  hw-iterate chart <loop-id>

The file is JSON:

  {"loop": "loop-gain",
   "goal": "phase margin >= 60 deg without giving up bandwidth",
   "objective": {"metric": "pm_deg", "direction": "max",
                 "target": 60, "unit": "deg"},
   "track": [{"metric": "bw_hz", "limit": 1e6, "direction": "max",
              "unit": "Hz"}],
   "status": "converged",
   "iterations": [
     {"iteration": 1, "vars": {"Rf": 12000, "Cc": 4.7e-12},
      "metrics": {"pm_deg": 31, "bw_hz": 2.1e6},
      "verdict": "fail", "note": "baseline from the datasheet values"},
     ...]}

A `.jsonl` file of iteration records is also read, one object per line.
`verdict` is pass / fail / partial. `accepted: true` on the iteration that was
taken forward — otherwise the best iteration against the objective is marked."""


def _evo_load(data):
    """Accept the ledger object, a bare list of iterations, or JSONL rows."""
    if isinstance(data, dict):
        meta = data
        its = data.get("iterations") or []
    else:
        meta, its = {}, list(data or [])
        # A JSONL ledger may lead with a meta record carrying no metrics.
        if its and not (its[0].get("metrics") or its[0].get("vars")):
            meta = its.pop(0)
    out = []
    for i, r in enumerate(its, 1):
        if not isinstance(r, dict):
            continue
        out.append({
            "n": int(r.get("iteration") or i),
            "vars": {k: v for k, v in (r.get("vars") or {}).items()},
            "metrics": {k: v for k, v in (r.get("metrics") or {}).items()},
            "verdict": str(r.get("verdict") or "").lower(),
            "note": str(r.get("note") or ""),
            "accepted": bool(r.get("accepted")),
        })
    return meta, out


def _evo_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _evo_verdict_colour(v):
    return {"pass": PASS, "fail": FAIL, "partial": WARN}.get(v, SERIES[0])


def _clip(s_: str, n: int) -> str:
    s_ = str(s_)
    return s_ if len(s_) <= n else s_[:n - 1].rstrip() + "\u2026"


def _evo_fmt(v, unit=""):
    """`2100000, "Hz"` -> "2.1 MHz";  `66.6, "deg"` -> "66.6 deg".

    `si()` alone is not enough here. Told a unit it refuses to prefix, which is
    right for 41.7 uA and wrong for 2100000 Hz — the axis label then runs off
    the left of the panel and the reader sees "100000 Hz" for a 2.1 MHz
    bandwidth. Told to prefix, it produces "66.6deg". So: prefix only where a
    prefix is what an engineer would write, and always with a space.
    """
    if v is None:
        return "-"
    a = abs(v)
    if a >= 1000 or (0 < a < 0.01):
        # "2.1MHz", not "2.1M Hz" — the prefix belongs to the unit.
        return si(v, unit, scale=True)
    return f"{_trim(v)}{(' ' + unit) if unit else ''}"


def _evo_panel(o, x0, y0, w, h, xs, series, label, limit=None, direction="",
               unit="", accent=SERIES[0], notes=None):
    """One metric against iteration number. Shared x, own y, limit drawn."""
    pts = [(n, v) for n, v in zip(xs, series) if v is not None]
    if not pts:
        return
    ys = [v for _, v in pts] + ([limit] if limit is not None else [])
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.14 or (abs(hi) * 0.1 or 1.0)
    lo, hi = lo - pad, hi + pad
    lo_n, hi_n = min(xs), max(xs)

    def X(n):
        return x0 + (n - lo_n) / max(hi_n - lo_n, 1e-9) * w

    def Y(v):
        return y0 + h - (v - lo) / max(hi - lo, 1e-9) * h

    o.append(f'<line class="ax" x1="{x0}" y1="{y0 + h}" x2="{x0 + w}" '
             f'y2="{y0 + h}" stroke-width="1"/>')
    o.append(f'<line class="ax" x1="{x0}" y1="{y0}" x2="{x0}" '
             f'y2="{y0 + h}" stroke-width="1"/>')
    for v in (lo + pad, hi - pad):
        o.append(f'<text class="axf" x="{x0 - 6}" y="{Y(v) + 3.5:.1f}" '
                 f'text-anchor="end" font-size="10">'
                 f'{esc(_evo_fmt(v, unit))}</text>')
    o.append(f'<text class="axf" x="{x0}" y="{y0 - 6}" font-size="10.5">'
             f'{esc(label)}</text>')

    # The limit, and the side of it that is good. A metric plotted without its
    # limit is a number the reader has to look up somewhere else.
    if limit is not None:
        o.append(f'<line x1="{x0}" y1="{Y(limit):.1f}" x2="{x0 + w}" '
                 f'y2="{Y(limit):.1f}" stroke="{FAIL}" stroke-width="1" '
                 f'stroke-dasharray="4 3" opacity=".75"/>')
        # Above the line, not centred on it: the last data value is
        # direct-labelled at the same x, and a metric that ends up near its
        # limit — exactly the interesting case — put the two on top of
        # each other.
        o.append(f'<text x="{x0 + w + 4}" y="{Y(limit) - 4:.1f}" '
                 f'font-size="10" fill="{FAIL}">'
                 f'{esc(("min " if direction == "max" else "max ") + _evo_fmt(limit, unit))}'
                 f'</text>')

    o.append('<polyline points="' +
             " ".join(f"{X(n):.1f},{Y(v):.1f}" for n, v in pts) +
             f'" fill="none" stroke="{accent}" stroke-width="1.8" '
             f'stroke-linejoin="round"/>')
    for n, v in pts:
        note = (notes or {}).get(n, "")
        o.append(f'<circle cx="{X(n):.1f}" cy="{Y(v):.1f}" r="3" '
                 f'fill="{accent}"><title>iteration {n}: '
                 f'{esc(_evo_fmt(v, unit))}'
                 f'{" — " + esc(note) if note else ""}</title></circle>')
    # The last value, named at the end of the line rather than in a legend.
    ln, lv = pts[-1]
    o.append(f'<text x="{X(ln) + 6:.1f}" y="{Y(lv) + 4:.1f}" font-size="11" '
             f'font-weight="600" fill="{accent}">'
             f'{esc(_evo_fmt(lv, unit))}</text>')
    return X, Y


def chart_evolution(data, title, subtitle) -> str:
    meta, its = _evo_load(data)
    if not its:
        return "".join(head(W, 80, title or "Evolution",
                            "no iterations recorded")) + "</svg>"

    xs = [r["n"] for r in its]
    notes = {r["n"]: r["note"] for r in its}
    obj = meta.get("objective") or {}
    okey = obj.get("metric")
    if not okey:
        # No declared objective: take the first metric that every iteration has.
        common = set(its[0]["metrics"])
        for r in its[1:]:
            common &= set(r["metrics"])
        okey = sorted(common)[0] if common else None
    direction = (obj.get("direction") or "max").lower()
    target = _evo_num(obj.get("target"))
    ounit = obj.get("unit") or ""

    ovals = [_evo_num(r["metrics"].get(okey)) for r in its] if okey else []
    have = [(r, v) for r, v in zip(its, ovals) if v is not None]

    # Which iteration is the answer: the one explicitly accepted, else the best
    # against the objective. Never "the last one" — a loop that ended because it
    # ran out of budget usually did not end on its best pass.
    best = None
    accepted = next((r for r in its if r["accepted"]), None)
    if have:
        best = (max if direction == "max" else min)(have, key=lambda rv: rv[1])
    chosen = None
    if accepted is not None:
        chosen = (accepted, _evo_num(accepted["metrics"].get(okey)))
    elif best is not None:
        chosen = best

    tracks = list(meta.get("track") or [])
    if not tracks:
        seen = []
        for r in its:
            for k in r["metrics"]:
                if k != okey and k not in seen:
                    seen.append(k)
        tracks = [{"metric": k} for k in seen[:3]]
    # Filtered here, not in the drawing loop below: the height is computed from
    # len(tracks) before anything is drawn, so a track that is declared and
    # never measured would reserve a panel's worth of blank page.
    tracks = [t for t in tracks
              if t.get("metric") != okey
              and any(_evo_num(r["metrics"].get(t.get("metric"))) is not None
                      for r in its)][:3]

    var_names = []
    for r in its:
        for k in r["vars"]:
            if k not in var_names:
                var_names.append(k)
    var_names = var_names[:6]

    top = 62 if (title or subtitle) else 24
    obj_h = 168
    trk_h = 74
    # Kept in step with the layout below by hand, because head() needs the
    # height before anything is drawn: 20 for the "changed" caption plus 18 a
    # row, then 26 for the iteration ticks.
    var_h = (20 + 18 * len(var_names)) if var_names else 0
    height = top + obj_h + 30 + len(tracks) * (trk_h + 26) + var_h + 26

    # Two lines, never one long one. The goal is the human's sentence and the
    # outcome is the machine's; concatenated they run off the right edge of the
    # SVG, and an SVG does not wrap.
    line1 = subtitle or meta.get("goal") or ""
    line2 = ""
    if chosen and chosen[1] is not None:
        state = meta.get("status") or ""
        verdict = ""
        if target is not None:
            met = (chosen[1] >= target) if direction == "max" else (chosen[1] <= target)
            verdict = ",  target met" if met else ",  SHORT of target"
        word = "accepted" if accepted is not None else "best"
        line2 = (f"{len(its)} iterations  ·  {word} #{chosen[0]['n']}: "
                 f"{okey} {_evo_fmt(chosen[1], ounit)}{verdict}"
                 f"{('  ·  ' + state) if state else ''}")
        if accepted is not None and best is not None and best[0]["n"] != accepted["n"]:
            # Accepting something other than the best pass is a judgement, and
            # the reviewer is entitled to see that it was made.
            line2 += f"  ·  best was #{best[0]['n']} ({_evo_fmt(best[1], ounit)})"
    if line2:
        height += 17

    o = head(W, height, title or f'Design loop — {meta.get("loop", "")}',
             _clip(" ".join(str(line1).split()), 108))
    if line2:
        o.append(f'<text class="ink2" x="16" y="62" font-size="12">'
                 f'{esc(_clip(line2, 108))}</text>')
        top += 17
    # The variable names are right-anchored against the left margin, so the
    # margin has to fit the longest of them or they run off the edge of the
    # SVG — which is what "ldo_gated" and "comparator" did.
    x0 = max(58, min(120, int(max((len(v) for v in var_names), default=0) * 5.7) + 14))
    w = W - x0 - 96

    # --- the objective ---------------------------------------------------
    if okey and have:
        _evo_panel(o, x0, top, w, obj_h, xs, ovals,
                   f"{okey}{(' (' + ounit + ')') if ounit else ''}",
                   limit=target, direction=direction, unit=ounit,
                   accent=SERIES[0], notes=notes)
        lo_n, hi_n = min(xs), max(xs)
        ys = [v for v in ovals if v is not None] + ([target] if target is not None else [])
        lo, hi = min(ys), max(ys)
        pad = (hi - lo) * 0.14 or (abs(hi) * 0.1 or 1.0)
        lo, hi = lo - pad, hi + pad
        X = lambda n: x0 + (n - lo_n) / max(hi_n - lo_n, 1e-9) * w
        Y = lambda v: top + obj_h - (v - lo) / max(hi - lo, 1e-9) * obj_h

        # Verdict is never colour alone: the failing passes carry a cross as
        # well as a red ring, so the chart survives a mono print.
        for r, v in zip(its, ovals):
            if v is None:
                continue
            col = _evo_verdict_colour(r["verdict"])
            if r["verdict"] == "fail":
                cx, cy = X(r["n"]), Y(v)
                o.append(f'<path d="M{cx-3.4:.1f},{cy-3.4:.1f}L{cx+3.4:.1f},{cy+3.4:.1f}'
                         f'M{cx+3.4:.1f},{cy-3.4:.1f}L{cx-3.4:.1f},{cy+3.4:.1f}" '
                         f'stroke="{col}" stroke-width="1.6"/>')
            elif r["verdict"] == "partial":
                o.append(f'<circle cx="{X(r["n"]):.1f}" cy="{Y(v):.1f}" r="4.5" '
                         f'fill="none" stroke="{col}" stroke-width="1.4"/>')

        if chosen and chosen[1] is not None:
            cr, cv = chosen
            col = PASS if (target is None or
                           ((cv >= target) if direction == "max" else (cv <= target))) else WARN
            o.append(f'<circle cx="{X(cr["n"]):.1f}" cy="{Y(cv):.1f}" r="6.5" '
                     f'fill="none" stroke="{col}" stroke-width="2"/>')
            lbl = "accepted" if accepted is not None else "best"
            anchor = "end" if X(cr["n"]) > x0 + w * 0.7 else "start"
            dx = -9 if anchor == "end" else 9
            o.append(f'<text x="{X(cr["n"]) + dx:.1f}" y="{Y(cv) - 10:.1f}" '
                     f'text-anchor="{anchor}" font-size="11" font-weight="600" '
                     f'fill="{col}">#{cr["n"]} {lbl}</text>')

        # The plateau is the reason to stop, so say it on the chart rather than
        # leaving the reader to measure three dots with their eye.
        tail = [v for v in ovals[-3:] if v is not None]
        if len(tail) == 3:
            span = max(tail) - min(tail)
            scale_ = max(abs(v) for v in tail) or 1.0
            if span / scale_ < 0.02:
                o.append(f'<text class="ink2" x="{x0 + w}" y="{top + obj_h - 6}" '
                         f'text-anchor="end" font-size="10.5">'
                         f'last 3 within {span / scale_ * 100:.1f}% — plateau</text>')

    # --- the metrics it was allowed to cost ------------------------------
    y = top + obj_h + 30
    for i, t in enumerate(tracks):
        key = t.get("metric")
        vals = [_evo_num(r["metrics"].get(key)) for r in its]
        _evo_panel(o, x0, y + 14, w, trk_h, xs, vals,
                   f'{key}{(" (" + t["unit"] + ")") if t.get("unit") else ""}',
                   limit=_evo_num(t.get("limit")),
                   direction=(t.get("direction") or "max").lower(),
                   unit=t.get("unit") or "", accent=SERIES[(i + 1) % len(SERIES)],
                   notes=notes)
        y += trk_h + 26

    # --- what was actually changed ---------------------------------------
    # The point of the strip: an objective that moved without a variable moving
    # is measurement noise, and a variable that moved without the objective
    # moving is a knob that does nothing. Both are visible only side by side.
    if var_names:
        lo_n, hi_n = min(xs), max(xs)
        X = lambda n: x0 + (n - lo_n) / max(hi_n - lo_n, 1e-9) * w
        o.append(f'<text class="axf" x="{x0}" y="{y + 10}" font-size="10.5">'
                 f'changed</text>')
        y += 20
        for name in var_names:
            o.append(f'<text class="ink2" x="{x0 - 6}" y="{y + 4}" '
                     f'text-anchor="end" font-size="10.5">{esc(name)}</text>')
            prev = None
            for r in its:
                v = r["vars"].get(name)
                cx = X(r["n"])
                if v is None:
                    prev = None
                    continue
                moved = prev is None or v != prev
                o.append(f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="{3 if moved else 1.6}" '
                         f'fill="{INK2["light"]}" opacity="{1 if moved else .35}">'
                         f'<title>iteration {r["n"]}: {esc(name)} = '
                         f'{esc(_evo_fmt(_evo_num(v)) if _evo_num(v) is not None else str(v))}'
                         f'</title></circle>')
                prev = v
            first = next((r["vars"].get(name) for r in its
                          if r["vars"].get(name) is not None), None)
            last = next((r["vars"].get(name) for r in reversed(its)
                         if r["vars"].get(name) is not None), None)
            def _fmt(v):
                n_ = _evo_num(v)
                return _evo_fmt(n_) if n_ is not None else str(v)
            # A variable that never moved says so by being one value, not by
            # being written twice with an arrow between it.
            span = (f"{_fmt(first)} \u2192 {_fmt(last)}"
                    if _fmt(first) != _fmt(last) else _fmt(first))
            o.append(f'<text class="ink2" x="{x0 + w + 8}" y="{y + 4}" '
                     f'font-size="10.5">{esc(span)}</text>')
            y += 18

    # x axis, once, at the bottom of the stack
    lo_n, hi_n = min(xs), max(xs)
    for n in xs:
        cx = x0 + (n - lo_n) / max(hi_n - lo_n, 1e-9) * w
        o.append(f'<text class="axf" x="{cx:.1f}" y="{height - 12}" '
                 f'text-anchor="middle" font-size="10">{n}</text>')
    # To the right of the last tick, not on top of it.
    o.append(f'<text class="axf" x="{x0 + w + 10}" y="{height - 12}" '
             f'font-size="10.5">iteration</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
KINDS = {
    "budget": (chart_budget, BUDGET_SCHEMA),
    "corners": (chart_corners, CORNERS_SCHEMA),
    "trace": (chart_trace, TRACE_SCHEMA),
    "bode": (chart_bode, BODE_SCHEMA),
    "coverage": (chart_coverage, COVERAGE_SCHEMA),
    "waterfall": (chart_waterfall, WATERFALL_SCHEMA),
    "stackup": (chart_stackup, STACKUP_SCHEMA),
    "evolution": (chart_evolution, EVOLUTION_SCHEMA),
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Engineering plots as themed, direct-labelled SVG.")
    ap.add_argument("kind", choices=sorted(KINDS))
    ap.add_argument("data", nargs="?", help="a .csv or .json")
    ap.add_argument("--out", help="output .svg (default: stdout)")
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--schema", action="store_true",
                    help="print what this chart's data should look like")
    ap.add_argument("--xlabel", default="")
    ap.add_argument("--ylabel", default="")
    ap.add_argument("--logx", action="store_true")
    ap.add_argument("--mark", action="append",
                    help='annotate an x position: --mark "x=1e-3,label=turn-on"')
    cfg = ap.parse_args()

    fn, schema = KINDS[cfg.kind]
    if cfg.schema:
        print(schema)
        return 0
    if not cfg.data:
        print(f"hw-chart: {cfg.kind} needs a data file "
              f"(--schema shows what it wants)", file=sys.stderr)
        return 2
    if not os.path.exists(cfg.data):
        print(f"hw-chart: no such file: {cfg.data}", file=sys.stderr)
        return 2

    if cfg.kind == "evolution":
        svg = fn(read_object(cfg.data), cfg.title, cfg.subtitle)
    elif cfg.kind in ("trace", "bode"):
        svg = fn(read_rows(cfg.data), cfg.title, cfg.subtitle, cfg)
    else:
        svg = fn(read_rows(cfg.data), cfg.title, cfg.subtitle)

    if cfg.out:
        os.makedirs(os.path.dirname(os.path.abspath(cfg.out)), exist_ok=True)
        with open(cfg.out, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {cfg.out} ({len(svg):,} bytes, {svg.count('<')} elements)")
    else:
        print(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
