#!/usr/bin/env python3
"""Pre-route and pre-fabrication gate for a KiCad board.

Everything here is one of the failures written up in
`hw-verification/references/pcb-layout.md`, turned from prose somebody has to
remember into arithmetic that runs. Each check names its section there, because
the reasoning is worth reading once and the check is worth running every time.

    PCB-THERMVIA   a thermal-via array landing on opposite-side copper   (§3)
    PCB-TRACKW     a net class wider than the pads on its own nets       (§1)
    PCB-CLEAR      a clearance that violates itself inside a footprint   (§1)
    PCB-KEEPOUT    a keepout constant smaller than the part it guards    (§4)
    PCB-DECAP      decoupling loop length, worst first
    PCB-SILK       silkscreen across a pad
    PCB-REFTEXT    a reference designator nobody can read
    PCB-COURTYARD  overlapping courtyards, by real polygon area          (§5)
    PCB-REFPLANE   a signal layer with no reference plane next to it

**Net classes are not in the `.kicad_pcb`.** They live in the sibling
`.kicad_pro` under `net_settings.classes`, with assignment through
`netclass_patterns`. A board linter that looks for them in the board file finds
none and reports every board clean, which is the worst thing a gate can do. So
this reads both files and says which one it got its rules from.

Usage:
    pcb-lint hw/probe.kicad_pcb
    pcb-lint hw/probe.kicad_pcb --gate
    pcb-lint hw/probe.kicad_pcb --svg docs/design/pcb-lint.svg
    pcb-lint hw/probe.kicad_pcb --keepout J5=6.60

Read-only. Nothing here opens a `.kicad_*` file for writing.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sexpr as sx  # noqa: E402

DECAP_MM = 5.0
MIN_TEXT_MM = 0.8
MIN_TEXT_THICK_MM = 0.15
SILK_CLEARANCE_MM = 0.15
THERMAL_DRILL_MAX = 0.45

GND_RE = re.compile(r"^(GND|AGND|DGND|PGND|GNDA|GNDD|VSS\w*|0V|EARTH)$", re.I)
PWR_RE = re.compile(r"^(VCC\w*|VDD\w*|VBAT|VBUS|VIN|VREF\w*|\+?\d+V\d*|\d+V\d*)$", re.I)
CAP_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([pnumµ]?)\s*F?\s*$", re.I)
MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0}

CODES = ["PCB-THERMVIA", "PCB-TRACKW", "PCB-CLEAR", "PCB-KEEPOUT", "PCB-DECAP",
         "PCB-SILK", "PCB-REFTEXT", "PCB-COURTYARD", "PCB-REFPLANE"]


def finding(code, severity, what, where=None, refs=None, **extra) -> dict:
    f = {"code": code, "severity": severity, "what": what}
    if where is not None:
        f["where"] = {"x": round(where[0], 4), "y": round(where[1], 4)}
    if refs:
        f["refs"] = list(refs)
    f.update(extra)
    return f


def cap_farads(value: str):
    v = str(value).strip()
    m = CAP_RE.match(v)
    if m:
        return float(m.group(1)) * MULT.get(m.group(2).lower(), 1.0)
    m = re.match(r"^(\d+)([pnumµ])(\d+)$", v, re.I)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * MULT.get(m.group(2).lower(), 1.0)
    return None


# --------------------------------------------------------------------------
# Board model
# --------------------------------------------------------------------------
def rot(x, y, deg):
    r = math.radians(deg)
    return (x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r))


def _world(a, x, y):
    """Footprint-local (x, y) into board coordinates, given the footprint's at."""
    wx, wy = rot(x, y, a[2])
    return (a[0] + wx, a[1] + wy)


def pad_net(pad) -> str:
    """The net name on a pad.

    KiCad 9 writes `(net 5 "GND")`; KiCad 10 writes `(net "GND")`. Reading
    index 2 works on one and returns nothing on the other, so take the last
    string in the node — which is the name in both.
    """
    n = sx.find(pad, "net")
    if n is None:
        return ""
    for v in reversed(n[1:]):
        if isinstance(v, str):
            return v
    return ""


class Board:
    def __init__(self, path: str, project: str | None = None):
        self.path = path
        self.doc = sx.parse_file(path)
        self.pro, self.pro_path = self._load_project(project)
        self.footprints = [self._footprint(f) for f in sx.find_all(self.doc, "footprint")]

    # -- project -----------------------------------------------------------
    def _load_project(self, override):
        cand = override or os.path.splitext(self.path)[0] + ".kicad_pro"
        if os.path.exists(cand):
            try:
                with open(cand) as fh:
                    return json.load(fh), cand
            except (OSError, ValueError):
                pass
        return {}, None

    @property
    def rules(self) -> dict:
        return (self.pro.get("board", {})
                .get("design_settings", {}).get("rules", {}) or {})

    @property
    def net_classes(self) -> list[dict]:
        return (self.pro.get("net_settings", {}).get("classes") or [])

    def class_of(self, net_name: str) -> dict:
        """Which net class a net belongs to.

        Explicit assignment first, then the ordered pattern list, then the
        class literally named Default. KiCad's own precedence, and getting it
        wrong makes every width check meaningless.
        """
        ns = self.pro.get("net_settings", {})
        by_name = {c.get("name"): c for c in self.net_classes}
        direct = (ns.get("netclass_assignments") or {}).get(net_name)
        if direct and direct in by_name:
            return by_name[direct]
        for pat in ns.get("netclass_patterns") or []:
            if fnmatch.fnmatch(net_name, str(pat.get("pattern", ""))):
                c = by_name.get(pat.get("netclass"))
                if c:
                    return c
        return by_name.get("Default", {})

    # -- geometry ----------------------------------------------------------
    def _footprint(self, node) -> dict:
        a = sx.at(node) or (0.0, 0.0, 0.0)
        layer = str(sx.attr(node, "layer", 1, "F.Cu"))
        back = layer.startswith("B.")
        p = sx.props(node)
        pads = []
        for pd in sx.find_all(node, "pad"):
            pa = sx.at(pd)
            if pa is None:
                continue
            size = sx.find(pd, "size")
            drill = sx.find(pd, "drill")
            layers = [str(v) for v in (sx.find(pd, "layers") or ["layers"])[1:]]
            if not any(l.endswith(".Cu") or l == "*.Cu" for l in layers):
                continue  # paste- or mask-only pad: no copper, not our problem
            wx, wy = rot(pa[0], pa[1], a[2])
            pads.append({
                "number": str(pd[1]) if len(pd) > 1 else "",
                "attr": str(pd[2]) if len(pd) > 2 else "",
                "shape": str(pd[3]) if len(pd) > 3 else "",
                "lx": pa[0], "ly": pa[1],
                "x": a[0] + wx, "y": a[1] + wy,
                "w": float(size[1]) if size and len(size) > 2 else 0.0,
                "h": float(size[2]) if size and len(size) > 2 else 0.0,
                "rot": (a[2] + pa[2]) % 360.0,
                "drill": float(drill[1]) if drill and len(drill) > 1
                         and isinstance(drill[1], float) else 0.0,
                "net": pad_net(pd),
                "layers": layers,
                "through": "*.Cu" in layers or str(pd[2] if len(pd) > 2 else "")
                           in ("thru_hole", "np_thru_hole"),
            })
        return {
            "node": node,
            "lib_id": str(node[1]) if len(node) > 1 and isinstance(node[1], str) else "",
            "ref": str(p.get("Reference", "")),
            "value": str(p.get("Value", "")),
            "x": a[0], "y": a[1], "rot": a[2],
            "layer": layer, "back": back,
            "pads": pads,
            "courtyard": self._poly(node, a, "CrtYd"),
            "silk": self._silk(node, a),
        }

    def _poly(self, node, a, suffix) -> list[tuple[float, float]]:
        """Courtyard outline, from whichever primitive the library used.

        KiCad footprints express the same rectangle three ways depending on
        who drew them: an `fp_rect` (0402s, JST connectors), a chain of
        `fp_line`s (the SO family) or an `fp_poly`. Reading only one of them
        makes two thirds of a board look like it has no courtyard, which then
        reads as "overlap cannot be checked" on parts that are perfectly fine.
        """
        pts = []
        for poly in sx.find_all(node, "fp_poly"):
            if suffix in str(sx.attr(poly, "layer", 1, "")):
                for xy in sx.find_all(sx.find(poly, "pts") or ["pts"], "xy"):
                    pts.append(_world(a, float(xy[1]), float(xy[2])))
        if pts:
            return pts
        for r in sx.find_all(node, "fp_rect"):
            if suffix not in str(sx.attr(r, "layer", 1, "")):
                continue
            st, en = sx.find(r, "start"), sx.find(r, "end")
            if st and en:
                x1, y1, x2, y2 = float(st[1]), float(st[2]), float(en[1]), float(en[2])
                for c in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
                    pts.append(_world(a, *c))
        if pts:
            return pts
        segs = []
        for ln in sx.find_all(node, "fp_line"):
            if suffix not in str(sx.attr(ln, "layer", 1, "")):
                continue
            st, en = sx.find(ln, "start"), sx.find(ln, "end")
            if not (st and en):
                continue
            for n in (st, en):
                segs.append(_world(a, float(n[1]), float(n[2])))
        if not segs:
            return []
        xs = [q[0] for q in segs]; ys = [q[1] for q in segs]
        return [(min(xs), min(ys)), (max(xs), min(ys)),
                (max(xs), max(ys)), (min(xs), max(ys))]

    def _silk(self, node, a) -> list[tuple[float, float, float, float]]:
        """Every silkscreen stroke as a world-space segment.

        Lines, rectangles (as four segments) and polygons (as their edges) —
        the same three-primitive spread as the courtyard.
        """
        out = []
        for ln in sx.find_all(node, "fp_line"):
            if "SilkS" not in str(sx.attr(ln, "layer", 1, "")):
                continue
            st, en = sx.find(ln, "start"), sx.find(ln, "end")
            if st and en:
                p1 = _world(a, float(st[1]), float(st[2]))
                p2 = _world(a, float(en[1]), float(en[2]))
                out.append((p1[0], p1[1], p2[0], p2[1]))
        for r in sx.find_all(node, "fp_rect"):
            if "SilkS" not in str(sx.attr(r, "layer", 1, "")):
                continue
            st, en = sx.find(r, "start"), sx.find(r, "end")
            if not (st and en):
                continue
            x1, y1, x2, y2 = float(st[1]), float(st[2]), float(en[1]), float(en[2])
            corners = [_world(a, *c) for c in
                       ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
            for i in range(4):
                p1, p2 = corners[i], corners[(i + 1) % 4]
                out.append((p1[0], p1[1], p2[0], p2[1]))
        for poly in sx.find_all(node, "fp_poly"):
            if "SilkS" not in str(sx.attr(poly, "layer", 1, "")):
                continue
            cs = [_world(a, float(xy[1]), float(xy[2]))
                  for xy in sx.find_all(sx.find(poly, "pts") or ["pts"], "xy")]
            for i in range(len(cs)):
                p1, p2 = cs[i], cs[(i + 1) % len(cs)]
                out.append((p1[0], p1[1], p2[0], p2[1]))
        # Silk *text* over a pad is the common version of this defect — an
        # autoplacer drops a reference designator onto the part it names when
        # the courtyard is tight. Approximated as a box, 0.72 of the character
        # height per character wide, which is close enough for "is it on the
        # pad or beside it".
        for t in list(sx.find_all(node, "fp_text")) + \
                [n for n in (sx.prop_node(node, "Reference"),
                             sx.prop_node(node, "Value")) if n is not None]:
            if "SilkS" not in str(sx.attr(t, "layer", 1, "")):
                continue
            if sx.is_hidden(t) or sx.is_hidden_flag(t):
                continue
            text = ""
            for v in t[1:3]:
                if isinstance(v, str) and v not in ("reference", "value", "user"):
                    text = v
            ta = sx.at(t)
            if not text or ta is None:
                continue
            hgt = sx.text_size(t, 1.0) or 1.0
            half_w = 0.72 * hgt * len(text) / 2
            cx, cy = ta[0], ta[1]
            for dx in (-half_w, half_w):
                px, py = cx + dx, cy
                out.append((px, py - hgt / 2, px, py + hgt / 2))
            out.append((cx - half_w, cy, cx + half_w, cy))
        return out

    # -- board-level copper -------------------------------------------------
    def segments(self):
        for s in sx.find_all(self.doc, "segment"):
            st, en = sx.find(s, "start"), sx.find(s, "end")
            if st and en:
                yield (float(st[1]), float(st[2]), float(en[1]), float(en[2]),
                       str(sx.attr(s, "layer", 1, "")), pad_net(s),
                       float(sx.attr(s, "width", 1, 0.0) or 0.0))

    def zones(self):
        for z in sx.find_all(self.doc, "zone"):
            layers = [str(v) for v in (sx.find(z, "layers") or ["layers"])[1:]]
            if not layers:
                one = sx.attr(z, "layer", 1, None)
                layers = [str(one)] if one else []
                pts = []
            for fp in sx.find_all(z, "filled_polygon"):
                pts = [(float(xy[1]), float(xy[2]))
                       for xy in sx.find_all(sx.find(fp, "pts") or ["pts"], "xy")]
                yield (layers, pad_net(z), pts)

    def copper_layers(self) -> list[tuple[str, str]]:
        lay = sx.find(self.doc, "layers")
        out = []
        for entry in (lay[1:] if lay else []):
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            name, kind = str(entry[1]), str(entry[2])
            if name.endswith(".Cu"):
                out.append((name, kind))
        return out

    def outline_bbox(self):
        xs, ys = [], []
        for g in sx.find_all(self.doc, "gr_line") + sx.find_all(self.doc, "gr_rect"):
            if "Edge.Cuts" not in str(sx.attr(g, "layer", 1, "")):
                continue
            for k in ("start", "end"):
                n = sx.find(g, k)
                if n and len(n) >= 3:
                    xs.append(float(n[1])); ys.append(float(n[2]))
        for g in sx.find_all(self.doc, "gr_arc") + sx.find_all(self.doc, "gr_poly"):
            if "Edge.Cuts" not in str(sx.attr(g, "layer", 1, "")):
                continue
            for xy in sx.find_all(sx.find(g, "pts") or ["pts"], "xy"):
                xs.append(float(xy[1])); ys.append(float(xy[2]))
        if not xs:
            for f in self.footprints:
                xs.append(f["x"]); ys.append(f["y"])
        if not xs:
            return (0.0, 0.0, 100.0, 100.0)
        return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------
def pad_rect(p) -> tuple[float, float, float, float]:
    """Axis-aligned box of a pad, exact at 0/90/180/270 and conservative else."""
    w, h = p["w"], p["h"]
    if abs((p["rot"] % 180) - 90) < 1e-6:
        w, h = h, w
    elif p["rot"] % 90 > 1e-6:
        d = math.hypot(w, h)
        w = h = d
    return (p["x"] - w / 2, p["y"] - h / 2, p["x"] + w / 2, p["y"] + h / 2)


def rect_gap(a, b) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def poly_area(pts) -> float:
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def clip(subject, clipper):
    """Sutherland-Hodgman. Both polygons must be convex-ish; courtyards are.

    A real intersection, not a bounding box, because §5 of pcb-layout.md is a
    whole section about `score_placement` inventing four 24 mm2 overlaps on an
    annular part by using its bbox. A check whose reason to exist is not lying
    cannot itself be a bbox test.
    """
    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def inter(p1, p2, a, b):
        x1, y1 = p1; x2, y2 = p2; x3, y3 = a; x4, y4 = b
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    if len(clipper) < 3 or len(subject) < 3:
        return []
    if poly_signed(clipper) < 0:
        clipper = clipper[::-1]
    out = list(subject)
    for i in range(len(clipper)):
        a, b = clipper[i], clipper[(i + 1) % len(clipper)]
        src, out = out, []
        for j in range(len(src)):
            cur, prv = src[j], src[j - 1]
            if inside(cur, a, b):
                if not inside(prv, a, b):
                    out.append(inter(prv, cur, a, b))
                out.append(cur)
            elif inside(prv, a, b):
                out.append(inter(prv, cur, a, b))
        if not out:
            return []
    return out


def poly_signed(pts) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2


def point_in_poly(px, py, pts) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xi = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xi:
                inside = not inside
    return inside


def seg_rect_dist(x1, y1, x2, y2, r) -> float:
    """Shortest distance from a segment to an axis-aligned rectangle.

    Zero when they touch. The naive version — distance from the pad centre to
    the segment, against half the pad's larger dimension — treats every pad as
    a circle round its long axis and reports a silk outline running alongside
    an SO package as ink on the pads. It is wrong on exactly the case this
    check exists for.
    """
    if _seg_hits_rect(x1, y1, x2, y2, r):
        return 0.0
    corners = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
    d = min(seg_point_dist(cx, cy, x1, y1, x2, y2) for cx, cy in corners)
    for px, py in ((x1, y1), (x2, y2)):
        cx = min(max(px, r[0]), r[2])
        cy = min(max(py, r[1]), r[3])
        d = min(d, math.hypot(px - cx, py - cy))
    return d


def _seg_hits_rect(x1, y1, x2, y2, r) -> bool:
    if r[0] <= x1 <= r[2] and r[1] <= y1 <= r[3]:
        return True
    if r[0] <= x2 <= r[2] and r[1] <= y2 <= r[3]:
        return True
    edges = [(r[0], r[1], r[2], r[1]), (r[2], r[1], r[2], r[3]),
             (r[2], r[3], r[0], r[3]), (r[0], r[3], r[0], r[1])]
    return any(_cross(x1, y1, x2, y2, *e) for e in edges)


def _cross(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    def side(px, py, qx, qy, rx, ry):
        v = (qx - px) * (ry - py) - (qy - py) * (rx - px)
        return (v > 1e-12) - (v < -1e-12)
    d1 = side(ax, ay, bx, by, cx, cy)
    d2 = side(ax, ay, bx, by, dx, dy)
    d3 = side(cx, cy, dx, dy, ax, ay)
    d4 = side(cx, cy, dx, dy, bx, by)
    return d1 != d2 and d3 != d4


def seg_point_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_thermvia(b: Board, cfg) -> list[dict]:
    """§3. A thermal-via array punches through and lands on the other side.

    Nothing in the placement flow knows a footprint contains vias.
    `score_placement` reasons about courtyards, and a via is not a courtyard.
    On one board this was 47 shorting pairs against a MOSFET drain and a
    hall-sensor network, and it reaches fabrication if nobody looks.
    """
    out = []
    clearance = float(b.rules.get("min_clearance") or 0.2) or 0.2
    for fp in b.footprints:
        vias = [p for p in fp["pads"]
                if p["through"] and 0 < p["drill"] <= THERMAL_DRILL_MAX]
        named = "ThermalVias" in fp["lib_id"]
        if not vias or not (named or any(not p["through"] for p in fp["pads"])):
            continue
        for other in b.footprints:
            if other is fp or other["back"] == fp["back"]:
                continue
            for v in vias:
                vr = (v["x"] - v["w"] / 2 - clearance, v["y"] - v["h"] / 2 - clearance,
                      v["x"] + v["w"] / 2 + clearance, v["y"] + v["h"] / 2 + clearance)
                for op in other["pads"]:
                    if op["net"] and v["net"] and op["net"] == v["net"]:
                        continue
                    if rect_gap(vr, pad_rect(op)) <= 0:
                        out.append(finding(
                            "PCB-THERMVIA", "ERROR",
                            f"{fp['ref']} has a via array under its exposed pad "
                            f"({v['net'] or 'no net'}) landing on {other['ref']} "
                            f"pad {op['number']} ({op['net'] or 'no net'}) on the "
                            f"other side — a short, and it reaches fabrication",
                            (v["x"], v["y"]), refs=[fp["ref"], other["ref"]],
                            section="pcb-layout.md §3"))
        for layers, net, pts in b.zones():
            if not pts:
                continue
            other_side = any((l.startswith("B.") if not fp["back"]
                              else l.startswith("F.")) for l in layers)
            if not other_side:
                continue
            for v in vias:
                if net and v["net"] and net == v["net"]:
                    continue
                if point_in_poly(v["x"], v["y"], pts):
                    out.append(finding(
                        "PCB-THERMVIA", "ERROR",
                        f"{fp['ref']}'s via array lands inside the "
                        f"{net or 'unnamed'} pour on the other side",
                        (v["x"], v["y"]), refs=[fp["ref"]],
                        section="pcb-layout.md §3"))
                    break
    return _dedupe(out)


def _dedupe(items):
    seen, out = set(), []
    for f in items:
        key = (f["code"], f["what"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def check_trackw(b: Board, cfg) -> list[dict]:
    """§1. A net class asking for a track no pad on its nets can accept.

    Not an error and not a DRC violation — simply unroutable, and it presents
    as a router returning almost every connection as a failure with no
    explanation. "180 of 234 connections unroutable" is what this looks like.
    """
    if not b.net_classes:
        return []
    worst: dict = {}
    for fp in b.footprints:
        for p in fp["pads"]:
            if not p["net"]:
                continue
            w = min(p["w"], p["h"])
            if w <= 0:
                continue
            cur = worst.get(p["net"])
            if cur is None or w < cur[0]:
                worst[p["net"]] = (w, fp["ref"], p["number"], (p["x"], p["y"]))
    out = []
    for net, (w, ref, num, where) in sorted(worst.items(), key=lambda kv: kv[1][0]):
        cls = b.class_of(net)
        tw = float(cls.get("track_width") or 0.0)
        if tw and tw > w + 1e-6:
            out.append(finding(
                "PCB-TRACKW", "ERROR",
                f"{cls.get('name', '?')} class asks for {tw:.2f} mm track on "
                f"{net}, and {ref} pad {num} is {w:.2f} mm wide — "
                f"{tw / w:.1f}x. Route at pad width, then widen and re-run DRC.",
                where, refs=[ref], net=net, track_width=tw, pad_width=round(w, 3),
                section="pcb-layout.md §1"))
    return out


def check_clear(b: Board, cfg) -> list[dict]:
    """§1. A clearance that violates itself inside a footprint.

    A Power class at 0.30 mm against a VSON-10's 0.255 mm pad-to-pad gap makes
    the part unreachable before a track exists, and DRC reports clearance
    errors inside a component nobody has touched.
    """
    if not b.net_classes:
        return []
    out = []
    for fp in b.footprints:
        pads = [p for p in fp["pads"] if p["w"] > 0 and p["h"] > 0]
        worst = None
        for i in range(len(pads)):
            for j in range(i + 1, len(pads)):
                a, c = pads[i], pads[j]
                if a["net"] and c["net"] and a["net"] == c["net"]:
                    continue
                if a["number"] and a["number"] == c["number"]:
                    continue
                g = rect_gap(pad_rect(a), pad_rect(c))
                if worst is None or g < worst[0]:
                    worst = (g, a, c)
        if worst is None:
            continue
        gap, a, c = worst
        for pad in (a, c):
            if not pad["net"]:
                continue
            cls = b.class_of(pad["net"])
            cl = float(cls.get("clearance") or 0.0)
            if cl and cl > gap + 1e-6:
                out.append(finding(
                    "PCB-CLEAR", "ERROR",
                    f"{cls.get('name', '?')} class clearance {cl:.2f} mm on "
                    f"{pad['net']} is wider than {fp['ref']}'s own pad gap "
                    f"({gap:.3f} mm between pads {a['number']} and "
                    f"{c['number']}) — the part is unreachable",
                    (fp["x"], fp["y"]), refs=[fp["ref"]],
                    clearance=cl, pad_gap=round(gap, 4),
                    section="pcb-layout.md §1"))
                break
    return out


def check_keepout(b: Board, cfg) -> list[dict]:
    """§4. A keepout radius written from memory, not read from the footprint.

    `RING_R = 6.60` guarding a part whose pads reach 8.50 mm protects bare
    laminate and leaves the pads exposed. DRC finds it; inspection does not,
    because the number looks plausible.
    """
    out = []
    for spec in cfg.keepout:
        if "=" not in spec:
            continue
        ref, val = spec.split("=", 1)
        try:
            declared = float(val)
        except ValueError:
            continue
        fp = next((f for f in b.footprints if f["ref"] == ref.strip()), None)
        if fp is None:
            out.append(finding("PCB-KEEPOUT", "WARN",
                               f"--keepout names {ref}, which is not on this board"))
            continue
        r = 0.0
        for p in fp["pads"]:
            half = math.hypot(p["w"], p["h"]) / 2
            r = max(r, math.hypot(p["x"] - fp["x"], p["y"] - fp["y"]) + half)
        if declared < r - 1e-6:
            out.append(finding(
                "PCB-KEEPOUT", "ERROR",
                f"keepout {declared:.2f} mm guards {ref}, whose outermost pad "
                f"reaches {r:.2f} mm — {r - declared:.2f} mm of pad is outside "
                f"the keepout. Read the dimension from the footprint.",
                (fp["x"], fp["y"]), refs=[ref], declared=declared,
                actual=round(r, 3), section="pcb-layout.md §4"))
    return out


def check_decap(b: Board, cfg) -> list[dict]:
    """Decoupling loop length, worst first.

    Every extra millimetre is inductance. A ranking rather than a verdict, so
    it does not gate unless asked: what matters is which cap is worst, and by
    how much, not a pass/fail on a number that varies with the rail.
    """
    caps = []
    for fp in b.footprints:
        if not fp["ref"].startswith("C"):
            continue
        f = cap_farads(fp["value"])
        if f is None or not (0 < f <= 1e-6):
            continue
        pwr = [p for p in fp["pads"] if PWR_RE.match(p["net"] or "")]
        gnd = [p for p in fp["pads"] if GND_RE.match(p["net"] or "")]
        if pwr and gnd:
            caps.append((fp, pwr[0], gnd[0]))

    ics = [f for f in b.footprints
           if len(f["pads"]) >= 6 and f["ref"].startswith(("U", "IC"))]
    out = []
    ranked = []
    for fp, cp, cg in caps:
        best = None
        for ic in ics:
            for p in ic["pads"]:
                if p["net"] != cp["net"]:
                    continue
                d = math.hypot(p["x"] - cp["x"], p["y"] - cp["y"])
                if best is None or d < best[0]:
                    best = (d, ic, p)
        if best is None:
            continue
        d, ic, p = best
        gnd_ret = None
        for other in b.footprints:
            for op in other["pads"]:
                if not GND_RE.match(op["net"] or ""):
                    continue
                if other is fp:
                    continue
                dd = math.hypot(op["x"] - cg["x"], op["y"] - cg["y"])
                if gnd_ret is None or dd < gnd_ret:
                    gnd_ret = dd
        loop = d + (gnd_ret or 0.0)
        ranked.append((loop, d, gnd_ret or 0.0, fp, ic, p))

    ranked.sort(key=lambda r: -r[0])
    for loop, d, ret, fp, ic, p in ranked:
        if loop <= cfg.decap_mm:
            continue
        sev = "ERROR" if loop > 3 * cfg.decap_mm else "WARN"
        out.append(finding(
            "PCB-DECAP", sev,
            f"{fp['ref']} -> {ic['ref']}.{p['number']} loop is {loop:.1f} mm "
            f"({d:.1f} mm to the power pad + {ret:.1f} mm of ground return) "
            f"against a {cfg.decap_mm:.1f} mm budget",
            (fp["x"], fp["y"]), refs=[fp["ref"], ic["ref"]],
            loop_mm=round(loop, 2), to_power_mm=round(d, 2),
            ground_return_mm=round(ret, 2)))
    return out


def check_silk(b: Board, cfg) -> list[dict]:
    """Silkscreen on a pad.

    Only an actual overlap is a defect. KiCad's own IPC-derived passive
    footprints put the silk bar 0.105 mm from an 0402 pad — under the 0.15 mm
    default clearance and perfectly normal — so a check that fires on
    proximity fires on every board with a capacitor on it, which is every
    board. Near-misses are reported only under --strict, with the measured
    distance, so the number can be taken to a fab rather than argued about.
    """
    out = []
    clearance = float(b.rules.get("min_silk_clearance") or 0.0) or SILK_CLEARANCE_MM
    for fp in b.footprints:
        overlaps, near, closest = 0, 0, None
        for (x1, y1, x2, y2) in fp["silk"]:
            best = None
            for other in b.footprints:
                if other["back"] != fp["back"]:
                    continue
                for pd in other["pads"]:
                    # A non-plated hole is not a solder joint, so ink across a
                    # mounting hole is not a solder defect. Without this every
                    # board with a silk outline near a mounting hole reports an
                    # error, which is how a real finding gets ignored.
                    if pd["attr"] == "np_thru_hole":
                        continue
                    d = seg_rect_dist(x1, y1, x2, y2, pad_rect(pd))
                    if best is None or d < best:
                        best = d
            if best is None:
                continue
            closest = best if closest is None else min(closest, best)
            if best <= 1e-9:
                overlaps += 1
            elif best < clearance:
                near += 1
        if overlaps:
            out.append(finding(
                "PCB-SILK", "ERROR",
                f"{fp['ref']} has {overlaps} silkscreen stroke(s) crossing a pad "
                f"— ink on a pad is a solder defect",
                (fp["x"], fp["y"]), refs=[fp["ref"]], overlaps=overlaps))
        elif near and cfg.strict:
            out.append(finding(
                "PCB-SILK", "WARN",
                f"{fp['ref']} silk comes within {closest:.3f} mm of a pad against "
                f"a {clearance:.2f} mm clearance — check the fab can hold it",
                (fp["x"], fp["y"]), refs=[fp["ref"]],
                closest_mm=round(closest, 4)))
    return out


def check_reftext(b: Board, cfg) -> list[dict]:
    min_h = float(b.rules.get("min_text_height") or cfg.min_text_mm)
    min_t = float(b.rules.get("min_text_thickness") or MIN_TEXT_THICK_MM)
    out, hidden = [], []
    for fp in b.footprints:
        pn = sx.prop_node(fp["node"], "Reference")
        if pn is None:
            continue
        if sx.is_hidden(pn) or sx.is_hidden_flag(pn):
            hidden.append(fp["ref"])
            continue
        layer = str(sx.attr(pn, "layer", 1, ""))
        if "SilkS" not in layer:
            hidden.append(fp["ref"])
            continue
        h = sx.text_size(pn, None)
        th = sx.find(pn, "effects", "font", "thickness")
        thick = float(th[1]) if th and len(th) > 1 else None
        if h is not None and h < min_h - 1e-6:
            out.append(finding("PCB-REFTEXT", "WARN",
                               f"{fp['ref']} is {h:.2f} mm high on silk against a "
                               f"{min_h:.2f} mm minimum — the assembler cannot read it",
                               (fp["x"], fp["y"]), refs=[fp["ref"]], height=h))
        elif thick is not None and thick < min_t - 1e-6:
            out.append(finding("PCB-REFTEXT", "WARN",
                               f"{fp['ref']} silk stroke is {thick:.2f} mm against a "
                               f"{min_t:.2f} mm minimum",
                               (fp["x"], fp["y"]), refs=[fp["ref"]]))
    if len(hidden) > 2:
        out.append(finding("PCB-REFTEXT", "WARN",
                           f"{len(hidden)} reference designator(s) are hidden or off "
                           f"silk ({', '.join(sorted(hidden)[:8])}"
                           f"{'…' if len(hidden) > 8 else ''}) — nobody can find a "
                           f"part on the assembled board",
                           refs=sorted(hidden)[:8]))
    return out


def check_courtyard(b: Board, cfg) -> list[dict]:
    out = []
    fps = [f for f in b.footprints if len(f["courtyard"]) >= 3]
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            a, c = fps[i], fps[j]
            if a["back"] != c["back"]:
                continue
            if abs(a["x"] - c["x"]) > 60 or abs(a["y"] - c["y"]) > 60:
                continue
            inter = clip(a["courtyard"], c["courtyard"])
            area = poly_area(inter)
            if area > 0.05:
                out.append(finding(
                    "PCB-COURTYARD", "ERROR",
                    f"{a['ref']} and {c['ref']} courtyards overlap by "
                    f"{area:.2f} mm² (real polygon area, not a bounding box)",
                    (a["x"], a["y"]), refs=[a["ref"], c["ref"]],
                    area_mm2=round(area, 3), section="pcb-layout.md §5"))
    no_crtyd = [f["ref"] for f in b.footprints if len(f["courtyard"]) < 3]
    if no_crtyd:
        out.append(finding("PCB-COURTYARD", "WARN",
                           f"{len(no_crtyd)} footprint(s) have no courtyard "
                           f"({', '.join(sorted(no_crtyd)[:6])}) — overlap cannot "
                           f"be checked for them at all",
                           refs=sorted(no_crtyd)[:6]))
    return out


def check_refplane(b: Board, cfg) -> list[dict]:
    """A signal layer with no reference plane next to it.

    Suppressed on two-layer boards unless --strict: there, a signal layer with
    a pour opposite it is the normal and correct arrangement, and warning about
    it every run is how a gate gets ignored.
    """
    layers = b.copper_layers()
    if len(layers) <= 2 and not cfg.strict:
        return []
    poured = set()
    for names, net, pts in b.zones():
        if GND_RE.match(net or "") or PWR_RE.match(net or ""):
            poured.update(names)
    out = []
    for idx, (name, kind) in enumerate(layers):
        if kind != "signal":
            continue
        neighbours = []
        if idx > 0:
            neighbours.append(layers[idx - 1])
        if idx + 1 < len(layers):
            neighbours.append(layers[idx + 1])
        ok = any(k in ("power", "mixed") or n in poured for n, k in neighbours)
        if not ok:
            out.append(finding(
                "PCB-REFPLANE", "WARN",
                f"{name} is a signal layer with no reference plane next to it "
                f"(neighbours: {', '.join(n for n, _ in neighbours) or 'none'}) — "
                f"return current has nowhere continuous to go",
                layer=name))
    return out


# --------------------------------------------------------------------------
# SVG: the board, with the decoupling loops drawn on it
# --------------------------------------------------------------------------
SEV_COLOUR = {"ERROR": "#d03b3b", "WARN": "#e08a1e"}
RAMP = ["#2c7d59", "#7a9b3c", "#c9a227", "#d97a25", "#c23b22"]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _spread(findings, r_ring=3.2):
    """Nudge markers that share a spot onto a small ring around it.

    Five findings on one part is normal — a footprint that is wrong is usually
    wrong in several ways — and five circles at identical coordinates is an
    unreadable knot rather than five findings.
    """
    seen: dict = {}
    out = []
    for f in findings:
        if "where" not in f:
            out.append((f, None))
            continue
        key = (round(f["where"]["x"], 1), round(f["where"]["y"], 1))
        n = seen.get(key, 0)
        seen[key] = n + 1
        if n == 0:
            out.append((f, (f["where"]["x"], f["where"]["y"])))
        else:
            ang = math.radians(50 * n - 90)
            r = r_ring + 0.3 * r_ring * (n // 7)
            out.append((f, (f["where"]["x"] + r * math.cos(ang),
                            f["where"]["y"] + r * math.sin(ang))))
    return out


def _wrap(text, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def board_svg(b: Board, findings, cfg) -> str:
    """The board, its decoupling loops, and every finding numbered on it.

    The legend goes *under* the board, not beside it. Beside it, a 40 mm board
    with a 68 mm legend column renders as a third board and two thirds text —
    which is the shape of a document, not of a picture of a board.
    """
    x0, y0, x1, y1 = b.outline_bbox()
    pad = 5.0
    bw, bh = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    # Marker size follows the board. A 1.7 mm circle is a sensible annotation
    # on a 160 mm motherboard and covers a whole part on a 40 mm module.
    mscale = max(0.45, min(2.2, bw / 55.0))
    marked = _spread([f for f in findings if f["code"] != "PCB-DECAP"],
                     r_ring=2.6 * mscale)
    # The legend is sized in board millimetres, so its type has to scale with
    # the board or a 40 mm board gets a legend three times its own height. Fix
    # the line length in characters and solve for the font size instead.
    cols = 2 if len(marked) > 4 else 1
    col_w = bw / cols
    chars = 54
    fs = max(0.7, min(2.0, (col_w - 2) / chars / 0.55))
    lh = fs * 1.55
    wrapped = []
    for i, (f, _pos) in enumerate(marked, 1):
        wrapped.append((f, _wrap(f"{i}. {f['what']}", chars)[:3]))
    per_col = max(1, (len(wrapped) + cols - 1) // cols)
    tallest = max((sum(len(l) + 0.35 for _f, l in
                       wrapped[c * per_col:(c + 1) * per_col])
                   for c in range(cols)), default=1)
    legend_h = 6.5 * fs + (tallest + 1) * lh
    total_h = bh + max(legend_h, 8.0)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{bw:.1f}mm" '
         f'height="{total_h:.1f}mm" viewBox="{x0 - pad:.2f} {y0 - pad:.2f} '
         f'{bw:.2f} {total_h:.2f}">',
         "<style>"
         ".bg{fill:#faf9f6}.edge{stroke:#5b6470;stroke-width:.25;fill:none}"
         ".fpF{fill:#8fb4d9;fill-opacity:.30;stroke:#4b7fae;stroke-width:.08}"
         ".fpB{fill:#d9a88f;fill-opacity:.30;stroke:#ae7f4b;stroke-width:.08}"
         ".ref{fill:#3c4650;font:1.3px sans-serif}"
         ".note{fill:#3c4650;font:2.0px sans-serif}"
         ".tiny{fill:#5b6470;font:1.4px sans-serif}"
         ".leg{font:1.5px sans-serif}"
         "@media (prefers-color-scheme:dark){.bg{fill:#14171a}.edge{stroke:#7e8a99}"
         ".ref,.note{fill:#c8d2dc}.tiny{fill:#93a1b0}}"
         "</style>",
         f'<rect class="bg" x="{x0 - pad:.2f}" y="{y0 - pad:.2f}" '
         f'width="{bw:.2f}" height="{total_h:.2f}"/>',
         f'<rect class="edge" x="{x0:.2f}" y="{y0:.2f}" '
         f'width="{x1 - x0:.2f}" height="{y1 - y0:.2f}"/>']

    for fp in b.footprints:
        cls = "fpB" if fp["back"] else "fpF"
        cy = fp["courtyard"]
        if len(cy) >= 3:
            pts = " ".join(f"{q[0]:.2f},{q[1]:.2f}" for q in cy)
            o.append(f'<polygon class="{cls}" points="{pts}"/>')
        for p in fp["pads"]:
            r = pad_rect(p)
            o.append(f'<rect class="{cls}" x="{r[0]:.2f}" y="{r[1]:.2f}" '
                     f'width="{r[2] - r[0]:.2f}" height="{r[3] - r[1]:.2f}"/>')
        o.append(f'<text class="ref" x="{fp["x"]:.2f}" y="{fp["y"] - 0.4:.2f}" '
                 f'text-anchor="middle">{esc(fp["ref"])}'
                 f'{" (B)" if fp["back"] else ""}</text>')

    loops = [f for f in findings if f["code"] == "PCB-DECAP"]
    worst = max([f.get("loop_mm", 0) for f in loops], default=1.0) or 1.0
    for f in loops:
        refs = f.get("refs", [])
        src = next((x for x in b.footprints if x["ref"] == refs[0]), None)
        dst = next((x for x in b.footprints
                    if len(refs) > 1 and x["ref"] == refs[1]), None)
        if not (src and dst):
            continue
        band = min(len(RAMP) - 1, int(len(RAMP) * f["loop_mm"] / (worst + 1e-9)))
        col = RAMP[band]
        o.append(f'<line x1="{src["x"]:.2f}" y1="{src["y"]:.2f}" '
                 f'x2="{dst["x"]:.2f}" y2="{dst["y"]:.2f}" stroke="{col}" '
                 f'stroke-width=".4" stroke-linecap="round">'
                 f'<title>{esc(f["what"])}</title></line>')
        mx, my = (src["x"] + dst["x"]) / 2, (src["y"] + dst["y"]) / 2
        o.append(f'<text class="tiny" x="{mx + 1.2:.2f}" y="{my:.2f}" '
                 f'fill="{col}">{f["loop_mm"]:.1f} mm</text>')

    for i, (f, pos) in enumerate(marked, 1):
        if pos is None:
            continue
        col = SEV_COLOUR.get(f["severity"], "#888")
        wx, wy = pos
        ax, ay = f["where"]["x"], f["where"]["y"]
        if abs(wx - ax) + abs(wy - ay) > 0.1:
            o.append(f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{wx:.2f}" '
                     f'y2="{wy:.2f}" stroke="{col}" '
                     f'stroke-width="{0.13 * mscale:.2f}" stroke-opacity=".6"/>')
        o.append(f'<circle cx="{wx:.2f}" cy="{wy:.2f}" r="{1.5 * mscale:.2f}" '
                 f'fill="{col}" fill-opacity=".14" stroke="{col}" '
                 f'stroke-width="{0.3 * mscale:.2f}"/>'
                 f'<text x="{wx:.2f}" y="{wy + 0.55 * mscale:.2f}" '
                 f'text-anchor="middle" fill="{col}" '
                 f'style="font:{1.6 * mscale:.2f}px sans-serif">{i}</text>'
                 f'<title>{esc(f["severity"])}: {esc(f["what"])}</title>')

    ly = y1 + pad + 1.9 * fs
    o.append(f'<line x1="{x0 - pad:.2f}" y1="{y1 + pad:.2f}" x2="{x1 + pad:.2f}" '
             f'y2="{y1 + pad:.2f}" stroke="#c7c2b6" stroke-width=".15"/>')
    errs = sum(1 for f in findings if f["severity"] == "ERROR")
    o.append(f'<text x="{x0 - pad + 1:.2f}" y="{ly:.2f}" fill="#3c4650" '
             f'style="font:bold {1.35 * fs:.2f}px sans-serif">'
             f'{esc(os.path.basename(b.path))} — {errs} error(s), '
             f'{len(findings) - errs} warning(s)</text>')
    if loops:
        ly += 1.7 * fs
        o.append(f'<text x="{x0 - pad + 1:.2f}" y="{ly:.2f}" fill="#5b6470" '
                 f'style="font:{0.95 * fs:.2f}px sans-serif">'
                 f'coloured lines are decoupling loops, longest darkest</text>')
    ly += 2.2 * fs
    col_top = ly
    for idx, (f, lines) in enumerate(wrapped):
        col = idx // per_col
        if idx % per_col == 0:
            ly = col_top
        cx = x0 - pad + 1 + col * col_w
        colour = SEV_COLOUR.get(f["severity"], "#888")
        for line in lines:
            o.append(f'<text x="{cx:.2f}" y="{ly:.2f}" fill="{colour}" '
                     f'style="font:{fs:.2f}px sans-serif">{esc(line)}</text>')
            ly += lh
        ly += lh * 0.35
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
def report(b: Board, findings, cfg) -> None:
    print(f"\nBoard lint — {b.path}\n")
    print(f"  {len(b.footprints)} footprint(s)   "
          f"{sum(len(f['pads']) for f in b.footprints)} pads   "
          f"{len(b.copper_layers())} copper layers")
    src = b.pro_path or "no .kicad_pro found"
    print(f"  rules and net classes from: {src}")
    if b.net_classes:
        print("  net classes: " + ", ".join(
            f"{c.get('name')} ({float(c.get('track_width', 0)):.2f} mm / "
            f"{float(c.get('clearance', 0)):.2f} mm)" for c in b.net_classes))
    else:
        print("  net classes: none — PCB-TRACKW and PCB-CLEAR cannot run")
    print()

    if not findings:
        print("  Nothing to report.\n")
        return
    by = defaultdict(list)
    for f in findings:
        by[(f["severity"], f["code"])].append(f)
    for (sev, code) in sorted(by, key=lambda k: (k[0] != "ERROR", k[1])):
        items = by[(sev, code)]
        sec = items[0].get("section", "")
        print(f"  {sev:<5}  {code} ({len(items)})"
              f"{'  — ' + sec if sec else ''}:")
        for f in items[:10]:
            print(f"    - {f['what']}")
        if len(items) > 10:
            print(f"    … and {len(items) - 10} more")
        print()
    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    print(f"  {errors} error(s), {len(findings) - errors} warning(s).")
    print("  --gate would " + ("fail." if errors else "pass.") + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-route gate for a KiCad board.")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--project", help="the .kicad_pro carrying the net classes")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--ignore", default="")
    ap.add_argument("--svg", metavar="OUT")
    ap.add_argument("--keepout", action="append", default=[], metavar="REF=MM",
                    help="a keepout radius to check against the real footprint")
    ap.add_argument("--decap-mm", type=float, default=DECAP_MM)
    ap.add_argument("--decap-gate", action="store_true",
                    help="let a long decoupling loop fail the gate")
    ap.add_argument("--min-text-mm", type=float, default=MIN_TEXT_MM)
    cfg = ap.parse_args()

    if not cfg.path:
        found = [os.path.join("hw", f) for f in sorted(os.listdir("hw"))
                 if f.endswith(".kicad_pcb")] if os.path.isdir("hw") else []
        if len(found) != 1:
            print(f"pcb-lint: name the .kicad_pcb ({len(found)} found under hw/)",
                  file=sys.stderr)
            return 2
        cfg.path = found[0]
    if not os.path.exists(cfg.path):
        print(f"pcb-lint: no such file: {cfg.path}", file=sys.stderr)
        return 2

    try:
        b = Board(cfg.path, cfg.project)
    except sx.SexprError as exc:
        print(f"pcb-lint: cannot read {cfg.path}: {exc}", file=sys.stderr)
        return 2

    only = {c.strip().upper() for c in cfg.only.split(",") if c.strip()}
    skip = {c.strip().upper() for c in cfg.ignore.split(",") if c.strip()}

    checks = [
        ("PCB-THERMVIA", check_thermvia), ("PCB-TRACKW", check_trackw),
        ("PCB-CLEAR", check_clear), ("PCB-KEEPOUT", check_keepout),
        ("PCB-DECAP", check_decap), ("PCB-SILK", check_silk),
        ("PCB-REFTEXT", check_reftext), ("PCB-COURTYARD", check_courtyard),
        ("PCB-REFPLANE", check_refplane),
    ]
    findings = []
    for code, fn in checks:
        if only and code not in only:
            continue
        if code in skip:
            continue
        findings += fn(b, cfg)

    if not cfg.decap_gate:
        for f in findings:
            if f["code"] == "PCB-DECAP":
                f["severity"] = "WARN"

    if cfg.svg:
        os.makedirs(os.path.dirname(os.path.abspath(cfg.svg)), exist_ok=True)
        with open(cfg.svg, "w", encoding="utf-8") as fh:
            fh.write(board_svg(b, findings, cfg))
        if not cfg.json:
            print(f"wrote {cfg.svg}")

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    if cfg.json:
        print(json.dumps({"file": cfg.path, "project": b.pro_path,
                          "findings": findings, "errors": errors,
                          "warnings": len(findings) - errors}, indent=2))
    else:
        report(b, findings, cfg)
    return 1 if (cfg.gate and errors) else 0


if __name__ == "__main__":
    sys.exit(main())
