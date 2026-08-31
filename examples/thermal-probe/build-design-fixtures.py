#!/usr/bin/env python3
"""Design-stage artefacts for the example project.

In a real project these come out of the tools: `vision-board` and build123d for
the CAD views, the SPICE and
CalculiX post-processing for the plots. None of those run in this container, so
these are written here in the same shapes and the same palette. The
schematic tab is the exception: it carries genuine `kicad-cli sch export svg`
output, exported by build-fixture.sh — the point is to
exercise the review page's handling of a 3D render, a chart, a contour plot
and a set of manufacturing drawings, which is what the artefact pipeline actually has to carry.

    python3 build-design-fixtures.py
"""
from __future__ import annotations

import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "design")

# The MakeHardware palette, so every fixture sits flush beside real output.
INK, INK2, MUTED, RULE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
OK, WAIT, STOP = "#0ca30c", "#2a78d6", "#d03b3b"
SURFACE = "#fcfcfb"
FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


def svg(width: float, height: float, body: str, label: str,
        extra_css: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="{FONT}" role="img" aria-label="{label}">'
        f"<style>"
        f".ink{{fill:{INK}}} .ink2{{fill:{INK2}}} .mut{{fill:{MUTED}}}"
        f".t{{font-size:11.5px}} .ts{{font-size:10px}} "
        f".tb{{font-size:12px;font-weight:600}} "
        f".h{{font-size:15px;font-weight:600}} "
        f".lbl{{font-size:10px;letter-spacing:0.09em;font-weight:600}}"
        f".num{{font-family:{MONO};font-size:10.5px}}"
        f"@media (prefers-color-scheme:dark){{"
        f".ink{{fill:#ffffff}} .ink2{{fill:#c3c2b7}}}}"
        f"{extra_css}</style>" + body + "</svg>")


# ---------------------------------------------------------------------------
# 1. CAD — isometric exploded view, projected from the declared envelope
# ---------------------------------------------------------------------------
COS30, SIN30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def iso(x: float, y: float, z: float, ox: float, oy: float, s: float):
    return (ox + (x - y) * COS30 * s, oy + (x + y) * SIN30 * s - z * s)


def iso_box(x, y, z, w, d, h, ox, oy, s, hue, alpha=1.0, label=""):
    """Three visible faces of an axis-aligned box, flat-shaded."""
    def P(*pts):
        return " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)

    top = [iso(x, y, z + h, ox, oy, s), iso(x + w, y, z + h, ox, oy, s),
           iso(x + w, y + d, z + h, ox, oy, s), iso(x, y + d, z + h, ox, oy, s)]
    left = [iso(x, y + d, z, ox, oy, s), iso(x, y + d, z + h, ox, oy, s),
            iso(x, y, z + h, ox, oy, s), iso(x, y, z, ox, oy, s)]
    right = [iso(x + w, y + d, z, ox, oy, s), iso(x + w, y + d, z + h, ox, oy, s),
             iso(x, y + d, z + h, ox, oy, s), iso(x, y + d, z, ox, oy, s)]

    def shade(base: str, k: float) -> str:
        r, g, b = (int(base[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(min(255, int(c * k)) for c in (r, g, b))

    o = [f'<g opacity="{alpha}">']
    for pts, k in ((right, 0.72), (left, 0.86), (top, 1.0)):
        o.append(f'<polygon points="{P(*pts)}" fill="{shade(hue, k)}" '
                 f'stroke="{INK}" stroke-width="0.7" stroke-linejoin="round"/>')
    o.append("</g>")
    return "\n".join(o)


def cad_exploded(bare: bool = False) -> str:
    """The enclosure, its board and its cell, pulled apart along Z.

    `bare` drops every label, which is what the rasterised copy uses. A real
    build123d or pcbnew render is geometry and nothing else — and a raster
    cannot follow the page's theme, so any text baked into one is dark-on-dark
    the moment the reader is in dark mode. Labels belong in the SVG or the
    caption, never in the bitmap.
    """
    s, ox, oy = 1.5, 215, 205
    body = ['<rect width="640" height="470" fill="none"/>']
    if not bare:
        body += [f'<text x="20" y="26" class="h ink">Enclosure, rev C — exploded</text>',
                 f'<text x="20" y="44" class="ts mut">'
                 f'from cad/enclosure.py · 38 × 164 × 22 mm envelope · '
                 f'components shown at their modelled positions</text>']
    # Drawn far-to-near so the painter's algorithm resolves correctly.
    parts = [(0, 0, 0, 38, 164, 2.0, "#8f8d86", 1.0, "Base", "1.8 mm wall"),
             (4, 52, 16, 30, 50, 3.8, "#2a78d6", 1.0, "Cell", "LP503035, 900 mAh"),
             (2.3, 34, 34, 33.4, 96, 1.6, "#0f9b8e", 1.0, "PCB", "33.4 × 96 mm"),
             (0, 0, 54, 38, 164, 2.0, "#c9c7bf", 0.92, "Lid", "with display window")]
    for px, py, pz, pw, pd, ph, hue, al, _n, _d in parts:
        body.append(iso_box(px, py, pz, pw, pd, ph, ox, oy, s, hue, alpha=al))

    # A keyed legend rather than labels on the geometry: an isometric stack
    # puts every part on the same diagonal, so leader text lands on top of the
    # next part down however it is offset.
    ly = 96
    for _x, _y, _z, _w, _d, _h, hue, _a, name, note in ([] if bare else reversed(parts)):
        body.append(f'<rect x="452" y="{ly - 9}" width="11" height="11" rx="2" '
                    f'fill="{hue}" stroke="{INK}" stroke-width="0.6"/>')
        body.append(f'<text x="470" y="{ly}" class="tb ink">{name}</text>')
        body.append(f'<text x="470" y="{ly + 14}" class="ts mut">{note}</text>')
        ly += 40
    if not bare:
        body.append(f'<text x="452" y="{ly + 6}" class="ts mut">'
                    f'split line at 40% depth</text>')
    return svg(640, 440, "\n".join(body),
               "Exploded isometric view of the enclosure, board and cell")


def cad_section() -> str:
    """A cross-section: the view a 3D viewer will not give you by default."""
    s = 2.6
    W, H = 38 * s, 22 * s
    ox, oy = 90, 90
    wall = 1.8 * s
    o = [f'<text x="20" y="26" class="h ink">Section A–A — internal stack</text>',
         f'<text x="20" y="44" class="ts mut">'
         f'through the cell pocket, looking up the long axis</text>']
    o.append(f'<rect x="{ox}" y="{oy}" width="{W}" height="{H}" fill="none" '
             f'stroke="{INK}" stroke-width="1.6"/>')
    o.append(f'<rect x="{ox + wall}" y="{oy + wall}" width="{W - 2 * wall}" '
             f'height="{H - 2 * wall}" fill="none" stroke="{INK2}" '
             f'stroke-width="1"/>')
    # cell then board, bottom-up
    cw, ch = 30 * s, 3.8 * s
    o.append(f'<rect x="{ox + (W - cw) / 2}" y="{oy + H - wall - ch}" '
             f'width="{cw}" height="{ch}" fill="#2a78d6" opacity="0.75"/>')
    bw, bh = 33.4 * s, 1.6 * s
    o.append(f'<rect x="{ox + (W - bw) / 2}" y="{oy + H - wall - ch - 6 - bh}" '
             f'width="{bw}" height="{bh}" fill="#0f9b8e" opacity="0.85"/>')
    labels = [("1.8 mm wall", oy + 14), ("PCB, 1.6 mm", oy + H - wall - ch - 12),
              ("cell, 3.8 mm", oy + H - wall - ch / 2 + 4)]
    for text, ly in labels:
        o.append(f'<line x1="{ox + W + 6}" y1="{ly - 4}" x2="{ox + W + 22}" '
                 f'y2="{ly - 4}" stroke="{MUTED}" stroke-width="0.7"/>')
        o.append(f'<text x="{ox + W + 28}" y="{ly}" class="ts ink2">{text}</text>')
    o.append(f'<text x="{ox}" y="{oy + H + 22}" class="num mut">'
             f'clearance board→lid 8.4 mm · board→cell 6.0 mm</text>')
    return svg(430, 190, "\n".join(o), "Cross-section of the enclosure stack")


# ---------------------------------------------------------------------------
# 2. Schematic sheet — the shape kicad-cli sch export svg produces
# ---------------------------------------------------------------------------
# 3. Simulation chart — magnitude against a limit, one series
# ---------------------------------------------------------------------------
CORNERS = [
    ("25 °C, 3.7 V nom", 12.4, True),
    ("−30 °C, 4.2 V max", 9.1, True),
    ("+40 °C, 3.5 V min", 31.8, True),
    ("+60 °C, 4.2 V max", 58.2, False),
]
LIMIT = 40.0


def standby_chart() -> str:
    """Four corners against a 40 uA cap.

    One series, so no legend — the title names it. The failing bar carries the
    status colour *and* the word FAIL, because state must never ride on hue
    alone. The limit is a reference line, not a fifth bar.
    """
    W, H = 660, 320
    left, top, right = 168, 96, 40
    bar_h, gap = 26, 18
    plot_w = W - left - right
    vmax = 70.0

    def x(v: float) -> float:
        return left + plot_w * v / vmax

    o = [f'<text x="20" y="28" class="h ink">Standby current by corner</text>',
         f'<text x="20" y="46" class="ts mut">'
         f'ngspice · sim/standby/standby.cir · run 2026-08-27 · '
         f'cross-checked against the closed-form leakage sum</text>']

    for gv in range(0, int(vmax) + 1, 10):
        gx = x(gv)
        o.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" '
                 f'y2="{top + len(CORNERS) * (bar_h + gap)}" stroke="{RULE}" '
                 f'stroke-width="1" opacity="0.45"/>')
        o.append(f'<text x="{gx:.1f}" y="{top - 14}" class="ts mut" '
                 f'text-anchor="middle">{gv}</text>')
    o.append(f'<text x="{left}" y="{top - 36}" class="lbl mut">'
             f'STANDBY CURRENT, MICROAMPS</text>')

    lx = x(LIMIT)
    o.append(f'<line x1="{lx:.1f}" y1="{top - 8}" x2="{lx:.1f}" '
             f'y2="{top + len(CORNERS) * (bar_h + gap)}" stroke="{INK2}" '
             f'stroke-width="1.6" stroke-dasharray="5 3"/>')
    o.append(f'<text x="{lx + 6:.1f}" y="{top + len(CORNERS) * (bar_h + gap) + 16}" '
             f'class="ts ink2">ELE-001 limit — 40 µA</text>')

    for i, (name, value, passes) in enumerate(CORNERS):
        by = top + i * (bar_h + gap)
        colour = OK if passes else STOP
        o.append(f'<text x="{left - 14}" y="{by + bar_h / 2 + 4}" class="t ink2" '
                 f'text-anchor="end">{name}</text>')
        o.append(f'<rect x="{left}" y="{by}" width="{x(value) - left:.1f}" '
                 f'height="{bar_h}" rx="4" fill="{colour}"/>')
        tag = f"{value} µA" + ("" if passes else "   ✕ FAIL")
        o.append(f'<text x="{x(value) + 9:.1f}" y="{by + bar_h / 2 + 4}" '
                 f'class="num" fill="{colour if not passes else INK2}" '
                 f'font-weight="{600 if not passes else 400}">{tag}</text>')

    o.append(f'<text x="20" y="{H - 20}" class="ts mut">'
             f'The +60 °C corner is outside the SYS-002 range of −30 to +40 °C '
             f'and is shown for information.</text>')
    return svg(W, H, "\n".join(o),
               "Standby current at four corners against the 40 microamp limit")


# ---------------------------------------------------------------------------
# 4. FEA — a sequential single-hue contour, with its colour bar
# ---------------------------------------------------------------------------
RAMP = ["#fdf0d5", "#fadCA0", "#f5bd6d", "#e89440", "#d1691f", "#a8460d"]


def thermal_map() -> str:
    """Steady-state rise over ambient across the board. One hue, light to dark."""
    W, H = 620, 330
    ox, oy, s = 40, 74, 2.6
    bw, bh = 33.4 * s, 96 * s / 2.4        # foreshortened, plan view
    nx, ny = 12, 16
    o = [f'<text x="20" y="28" class="h ink">Board temperature rise, steady state</text>',
         f'<text x="20" y="46" class="ts mut">'
         f'CalculiX · 21 °C ambient, still air, 12 mA continuous · '
         f'peak 14.2 K over ambient at U2</text>']

    # A smooth hot spot at the LDO, which is where the dissipation is.
    hx, hy = 0.62, 0.30
    for iy in range(ny):
        for ix in range(nx):
            u, v = (ix + 0.5) / nx, (iy + 0.5) / ny
            d = math.hypot((u - hx) * 1.5, v - hy)
            t = max(0.0, 1.0 - d * 1.9)
            band = min(len(RAMP) - 1, int(t * len(RAMP)))
            o.append(f'<rect x="{ox + u * bw - bw / nx / 2:.1f}" '
                     f'y="{oy + v * bh - bh / ny / 2:.1f}" '
                     f'width="{bw / nx + 0.6:.1f}" height="{bh / ny + 0.6:.1f}" '
                     f'fill="{RAMP[band]}"/>')
    o.append(f'<rect x="{ox}" y="{oy}" width="{bw:.1f}" height="{bh:.1f}" '
             f'fill="none" stroke="{INK}" stroke-width="1.2"/>')
    o.append(f'<circle cx="{ox + hx * bw:.1f}" cy="{oy + hy * bh:.1f}" r="5" '
             f'fill="none" stroke="{INK}" stroke-width="1.4"/>')
    o.append(f'<text x="{ox + hx * bw + 10:.1f}" y="{oy + hy * bh + 4:.1f}" '
             f'class="ts ink">U2 · 14.2 K</text>')

    # colour bar
    cbx, cby, cbw, cbh = 400, oy, 26, bh
    for i, col in enumerate(RAMP):
        seg = cbh / len(RAMP)
        o.append(f'<rect x="{cbx}" y="{cby + cbh - (i + 1) * seg:.1f}" '
                 f'width="{cbw}" height="{seg + 0.5:.1f}" fill="{col}"/>')
    o.append(f'<rect x="{cbx}" y="{cby}" width="{cbw}" height="{cbh:.1f}" '
             f'fill="none" stroke="{RULE}" stroke-width="1"/>')
    for i in range(len(RAMP) + 1):
        val = i * 15.0 / len(RAMP)
        yy = cby + cbh - i * cbh / len(RAMP)
        o.append(f'<text x="{cbx + cbw + 7}" y="{yy + 4:.1f}" class="num mut">'
                 f'{val:.1f}</text>')
    o.append(f'<text x="{cbx}" y="{cby - 12}" class="lbl mut">K OVER AMBIENT</text>')
    o.append(f'<text x="20" y="{H - 20}" class="ts mut">'
             f'MEC-004 caps the case at 20 K over ambient. Margin 5.8 K, at the '
             f'still-air corner.</text>')
    return svg(W, H, "\n".join(o), "Board temperature rise contour map")


# ---------------------------------------------------------------------------
# 5. Manufacturing — the stackup
# ---------------------------------------------------------------------------
LAYERS = [
    ("F.Mask", 0.015, "#0f9b8e", "soldermask"),
    ("F.Cu", 0.035, "#c08a2e", "1 oz copper"),
    ("Core", 1.510, "#d9d6cc", "FR-4 TG150"),
    ("B.Cu", 0.035, "#c08a2e", "1 oz copper"),
    ("B.Mask", 0.015, "#0f9b8e", "soldermask"),
]


def stackup() -> str:
    ox, oy, sw = 150, 80, 260
    scale = 110.0
    # Height follows the content: the row pitch grew when the labels moved to
    # one line each, and a fixed canvas simply cropped the bottom layer off.
    W = 620
    H = int(oy + sum(max(5.0, th * scale) + 14 for _n, th, _c, _t in LAYERS) + 56)
    o = [f'<text x="20" y="28" class="h ink">Stackup — 2 layer, 1.6 mm</text>',
         f'<text x="20" y="46" class="ts mut">'
         f'finished 1.62 mm ±10% · ENIG · min track/gap 0.15 mm · '
         f'min drill 0.30 mm</text>']
    y = oy
    for name, th, col, note in LAYERS:
        h = max(5.0, th * scale)
        o.append(f'<rect x="{ox}" y="{y:.1f}" width="{sw}" height="{h:.1f}" '
                 f'fill="{col}" stroke="{INK}" stroke-width="0.7"/>')
        o.append(f'<text x="{ox - 12}" y="{y + h / 2 + 4:.1f}" class="num ink2" '
                 f'text-anchor="end">{name}</text>')
        # One line, not two: the thin copper bands are 5 px tall and a stacked
        # pair of labels on each collided with its neighbours.
        o.append(f'<text x="{ox + sw + 14}" y="{y + h / 2 + 4:.1f}" class="ts ink2">'
                 f'{th:.3f} mm  ·  {note}</text>')
        o.append(f'<line x1="{ox + sw}" y1="{y + h / 2:.1f}" x2="{ox + sw + 10}" '
                 f'y2="{y + h / 2:.1f}" stroke="{MUTED}" stroke-width="0.6"/>')
        y += h + 14
    o.append(f'<line x1="{ox - 46}" y1="{oy}" x2="{ox - 46}" y2="{y - 2:.1f}" '
             f'stroke="{MUTED}" stroke-width="0.8"/>')
    o.append(f'<text x="{ox - 52}" y="{(oy + y) / 2:.1f}" class="num mut" '
             f'text-anchor="middle" transform="rotate(-90 {ox - 52} '
             f'{(oy + y) / 2:.1f})">1.610 mm</text>')
    o.append(f'<text x="20" y="{H - 20}" class="ts mut">'
             f'Not to scale in Z — copper is drawn at a floor so it stays '
             f'visible.</text>')
    return svg(W, H, "\n".join(o), "Two-layer PCB stackup")


# ---------------------------------------------------------------------------
# 6. Manufacturing — the drawings a fab and an assembler actually work from
# ---------------------------------------------------------------------------
# Board outline and placements as the layout declares them. Real projects get
# these from `kicad-cli pcb export pdf --layers Edge.Cuts,F.Fab` and from the
# position file; the shapes here are the same shapes so the review page carries
# the same load.
BOARD_W, BOARD_H = 62.0, 34.0                       # mm, from MEC-001

PLACEMENTS = [
    # ref, x, y, w, h, rot, part, polarised
    ("U1",  9.0,  7.0, 10.0,  6.0,   0, "STM32L0",     True),
    ("U2", 27.0,  6.5,  5.0,  5.0,   0, "MCP1700",     True),
    ("U3", 27.0, 20.0,  4.4,  3.0,   0, "REF3025",     True),
    ("U4", 44.0,  7.5,  6.0,  4.0,   0, "MAX31865",    True),
    ("J1",  3.0, 22.0,  9.0,  7.5,  90, "USB-C",       False),
    ("J2", 55.0, 12.0,  5.0, 10.0,  90, "Probe 4-pin", True),
    ("DS1", 40.0, 22.0, 16.0,  9.0,  0, "LCD 128x64",  True),
    ("BT1", 15.0, 20.0, 17.0, 11.0,  0, "18650 clip",  True),
    ("C6", 22.0, 13.0,  2.0,  1.2,   0, "100 nF",      False),
    ("C7", 34.0, 13.0,  2.0,  1.2,   0, "100 nF",      False),
]


def assembly_drawing() -> str:
    """Placement, orientation and polarity — what the assembler needs."""
    s, ox, oy = 8.0, 56, 74                          # px per mm
    W = int(ox * 2 + BOARD_W * s)
    H = int(oy + BOARD_H * s + 96)
    o = ['<text x="20" y="28" class="h ink">Assembly drawing — top side</text>',
         f'<text x="20" y="46" class="ts mut">{BOARD_W:.0f} x {BOARD_H:.0f} mm '
         f'· 10 placements · pin 1 and polarity marked · not to scale</text>']
    # The board face is a class, not a literal, so it follows the reader's
    # theme. Painted white it was a slab with white ref-designators on it.
    o.append(f'<rect x="{ox}" y="{oy}" width="{BOARD_W * s:.1f}" '
             f'height="{BOARD_H * s:.1f}" class="board" stroke="{INK}" '
             f'stroke-width="1.2" rx="6"/>')
    for gx in range(0, int(BOARD_W) + 1, 10):
        o.append(f'<line x1="{ox + gx * s:.1f}" y1="{oy}" x2="{ox + gx * s:.1f}" '
                 f'y2="{oy + BOARD_H * s:.1f}" stroke="{RULE}" '
                 f'stroke-width="0.4" stroke-dasharray="2 4"/>')
    for ref, x, y, w, h, rot, part, pol in PLACEMENTS:
        if rot == 90:
            w, h = h, w
        px, py = ox + x * s, oy + y * s
        o.append(f'<g><title>{ref} — {part}, {rot}°</title>'
                 f'<rect x="{px:.1f}" y="{py:.1f}" width="{w * s:.1f}" '
                 f'height="{h * s:.1f}" fill="none" stroke="{INK2}" '
                 f'stroke-width="1"/>')
        if pol:                                      # pin-1 dot, bottom-left
            o.append(f'<circle cx="{px + 5:.1f}" cy="{py + h * s - 5:.1f}" '
                     f'r="2.6" fill="{STOP}"/>')
        o.append(f'<text x="{px + w * s / 2:.1f}" y="{py + h * s / 2 + 3.5:.1f}" '
                 f'class="num ink" text-anchor="middle">{ref}</text></g>')
    base = oy + BOARD_H * s
    o.append(f'<line x1="{ox}" y1="{base + 22}" x2="{ox + BOARD_W * s:.1f}" '
             f'y2="{base + 22}" stroke="{MUTED}" stroke-width="0.8" '
             f'marker-start="url(#aa)" marker-end="url(#aa)"/>')
    o.append(f'<text x="{ox + BOARD_W * s / 2:.1f}" y="{base + 16}" '
             f'class="num mut" text-anchor="middle">{BOARD_W:.1f} mm</text>')
    o.append(f'<circle cx="26" cy="{base + 48}" r="2.6" fill="{STOP}"/>'
             f'<text x="36" y="{base + 52}" class="ts ink2">'
             f'Red dot marks pin 1 / anode / positive. Seven of the ten '
             f'placements are polarised.</text>')
    defs = (f'<defs><marker id="aa" markerWidth="7" markerHeight="7" refX="3.5" '
            f'refY="3.5" orient="auto"><path d="M0,3.5 L7,1 L7,6 z" '
            f'fill="{MUTED}"/></marker></defs>')
    css = (f".board{{fill:{SURFACE}}}"
           f"@media (prefers-color-scheme:dark){{.board{{fill:#191917}}}}")
    return svg(W, H, defs + "\n".join(o), "Assembly drawing, top side", css)


def fab_drawing() -> str:
    """Outline, holes and the tolerances the fab quotes against."""
    s, ox, oy = 8.0, 62, 74
    W = int(ox * 2 + BOARD_W * s)
    H = int(oy + BOARD_H * s + 118)
    holes = [(4.0, 4.0, 3.2, "M3 mount"), (58.0, 4.0, 3.2, "M3 mount"),
             (4.0, 30.0, 3.2, "M3 mount"), (58.0, 30.0, 3.2, "M3 mount"),
             (31.0, 30.5, 1.0, "test point")]
    o = ['<text x="20" y="28" class="h ink">Fabrication drawing</text>',
         '<text x="20" y="46" class="ts mut">Dimensions in mm. Outline '
         'tolerance ±0.15. Drill sizes are finished.</text>']
    o.append(f'<rect x="{ox}" y="{oy}" width="{BOARD_W * s:.1f}" '
             f'height="{BOARD_H * s:.1f}" fill="none" stroke="{INK}" '
             f'stroke-width="1.6" rx="6"/>')
    for hx, hy, d, what in holes:
        cx, cy = ox + hx * s, oy + hy * s
        r = max(3.0, d * s / 2)
        o.append(f'<g><title>{what} — ⌀{d:.1f} mm</title>'
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" '
                 f'stroke="{INK2}" stroke-width="1"/>'
                 f'<line x1="{cx - r - 4:.1f}" y1="{cy:.1f}" '
                 f'x2="{cx + r + 4:.1f}" y2="{cy:.1f}" stroke="{MUTED}" '
                 f'stroke-width="0.5"/>'
                 f'<line x1="{cx:.1f}" y1="{cy - r - 4:.1f}" x2="{cx:.1f}" '
                 f'y2="{cy + r + 4:.1f}" stroke="{MUTED}" '
                 f'stroke-width="0.5"/></g>')
    base = oy + BOARD_H * s
    o.append(f'<line x1="{ox}" y1="{base + 22}" x2="{ox + BOARD_W * s:.1f}" '
             f'y2="{base + 22}" stroke="{MUTED}" stroke-width="0.8" '
             f'marker-start="url(#ab)" marker-end="url(#ab)"/>')
    o.append(f'<text x="{ox + BOARD_W * s / 2:.1f}" y="{base + 16}" '
             f'class="num mut" text-anchor="middle">{BOARD_W:.1f}</text>')
    o.append(f'<line x1="{ox - 22}" y1="{oy}" x2="{ox - 22}" y2="{base:.1f}" '
             f'stroke="{MUTED}" stroke-width="0.8" marker-start="url(#ab)" '
             f'marker-end="url(#ab)"/>')
    o.append(f'<text x="{ox - 28}" y="{(oy + base) / 2:.1f}" class="num mut" '
             f'text-anchor="middle" transform="rotate(-90 {ox - 28} '
             f'{(oy + base) / 2:.1f})">{BOARD_H:.1f}</text>')
    rows = ["4 x \u23003.20 mm plated — M3 clearance, on a 54 x 26 mm pattern",
            "1 x \u23001.00 mm plated — VREF test point",
            "Min track / gap 0.15 mm  ·  min annular ring 0.13 mm",
            "ENIG finish, IPC-A-600 class 2, electrical test 100%"]
    for k, line in enumerate(rows):
        o.append(f'<text x="20" y="{base + 50 + k * 16}" class="ts ink2">'
                 f'{line}</text>')
    defs = (f'<defs><marker id="ab" markerWidth="7" markerHeight="7" refX="3.5" '
            f'refY="3.5" orient="auto"><path d="M0,3.5 L7,1 L7,6 z" '
            f'fill="{MUTED}"/></marker></defs>')
    return svg(W, H, defs + "\n".join(o), "Fabrication drawing")


# ---------------------------------------------------------------------------
def rasterise(svg_path: str, png_path: str, w: int, h: int) -> bool:
    """One fixture goes through as a PNG, to exercise the data-URI path.

    A real project's CAD and PCB renders are rasters, and the review page has
    to embed them under a byte budget rather than inline them as markup.
    """
    for chrome in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                   "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        if not os.path.exists(chrome):
            continue
        wrap = svg_path + ".html"
        with open(wrap, "w") as fh:
            fh.write(f'<!doctype html><body style="margin:0;background:none">'
                     f'<img src="file://{os.path.abspath(svg_path)}" '
                     f'style="display:block"></body>')
        try:
            # Transparent, so the render composites onto whatever the page's
            # theme paints behind it. An opaque render exported against white
            # is a bright slab on a dark page — which is what happens to most
            # real CAD and board renders, and why the page mats those.
            subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                            "--default-background-color=00000000",
                            f"--screenshot={png_path}", f"--window-size={w},{h}",
                            "--hide-scrollbars", f"file://{os.path.abspath(wrap)}"],
                           capture_output=True, timeout=90)
        finally:
            os.remove(wrap)
        return os.path.exists(png_path)
    return False


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "schematic"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "mfg"), exist_ok=True)
    files = {
        "cad/enclosure-exploded.svg": cad_exploded(),
        "cad/enclosure-section.svg": cad_section(),
        "standby-corners.svg": standby_chart(),
        "thermal-map.svg": thermal_map(),
        "stackup.svg": stackup(),
        "mfg/assembly-drawing.svg": assembly_drawing(),
        "mfg/fab-drawing.svg": fab_drawing(),
    }
    os.makedirs(os.path.join(OUT, "cad"), exist_ok=True)
    for rel, text in files.items():
        path = os.path.join(OUT, rel)
        with open(path, "w") as fh:
            fh.write(text)
        print(f"  wrote docs/design/{rel}  ({len(text) // 1024} kB)")

    # The raster is built from a label-free copy: see cad_exploded(bare=True).
    bare = os.path.join(OUT, "cad", ".enclosure-bare.svg")
    with open(bare, "w") as fh:
        fh.write(cad_exploded(bare=True))
    png = os.path.join(OUT, "cad", "enclosure-render.png")
    ok = rasterise(bare, png, 640, 440)
    os.remove(bare)
    if ok:
        print(f"  wrote docs/design/cad/enclosure-render.png  "
              f"({os.path.getsize(png) // 1024} kB)  [raster path]")
    else:
        print("  note: no chromium — skipped the PNG raster fixture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
