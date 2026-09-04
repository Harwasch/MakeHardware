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
    if path.endswith(".json"):
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else data.get("rows", [])
    with open(path, newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


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
KINDS = {
    "budget": (chart_budget, BUDGET_SCHEMA),
    "corners": (chart_corners, CORNERS_SCHEMA),
    "trace": (chart_trace, TRACE_SCHEMA),
    "bode": (chart_bode, BODE_SCHEMA),
    "coverage": (chart_coverage, COVERAGE_SCHEMA),
    "waterfall": (chart_waterfall, WATERFALL_SCHEMA),
    "stackup": (chart_stackup, STACKUP_SCHEMA),
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

    rows = read_rows(cfg.data)
    if cfg.kind in ("trace", "bode"):
        svg = fn(rows, cfg.title, cfg.subtitle, cfg)
    else:
        svg = fn(rows, cfg.title, cfg.subtitle)

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
