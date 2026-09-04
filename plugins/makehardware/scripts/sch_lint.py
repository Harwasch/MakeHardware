#!/usr/bin/env python3
"""Readability and structure gate for a KiCad schematic.

ERC answers "is this circuit electrically consistent". Nothing answers "can a
human read this", and that is the question that decides whether a review is a
review. A sheet with 900 symbols on it, wires at 37 degrees, `Net-(U2-Pad3)`
where a name should be and a decoupling capacitor drawn two sheets away from
the part it decouples is a *valid* schematic. It is also unreviewable, and an
agent will happily produce one because nothing ever told it not to.

So this reads the file and measures the things that make a schematic legible:

    SCH-GRID       symbols, pins, wires and labels on the 1.27 mm grid
    SCH-DIAG       wires orthogonal
    SCH-DENSITY    a sheet small enough to render, and to read
    SCH-TITLE      a title block with something in it
    SCH-REVSKEW    every sheet at the same revision
    SCH-TEXTSIZE   one text size, not five
    SCH-SHEETPIN   hierarchical pins matching the child's labels
    SCH-PWRDIR     rails drawn up, grounds drawn down
    SCH-AUTONET    every net that matters carries a name a human chose
    SCH-DECAP      decoupling drawn beside the pin it serves
    SCH-OVERLAP    nothing drawn on top of anything else
    SCH-ANNOT      designators counting left to right, top to bottom
    SCH-FLOW       signal flow left to right
    SCH-PLAN       every agreed block on exactly one sheet

Usage:
    sch-lint hw/probe.kicad_sch                  # report
    sch-lint hw/probe.kicad_sch --gate           # exit 1 on any ERROR
    sch-lint hw/probe.kicad_sch --json
    sch-lint hw/probe.kicad_sch --svg docs/design/lint
    sch-lint hw/probe.kicad_sch --plan hw/block-diagram.yaml

WARN never gates; ERROR always does. `--strict` promotes the soft checks.
`--only` and `--ignore` take comma-separated codes — a fourteen-check linter
without them gets `|| true`'d into a no-op the first time one check is noisy,
which is worse than not having it.

Reading a `.kicad_sch` is fine; writing one is not. Nothing here opens a file
for writing except the SVG it is asked for.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sexpr as sx  # noqa: E402

# --------------------------------------------------------------------------
# House defaults. Every one of these is a number someone can argue with, which
# is why they are all flags.
# --------------------------------------------------------------------------
GRID = 1.27                 # 50 mil. KiCad's default and every library's.
TOL = 1e-4
TEXT_SIZE = 1.27
TEXT_ALLOW = (1.524, 2.54)  # a sheet title and a section heading may be bigger
SVG_ELEMENT_BUDGET = 30_000  # exports.md: over this and the review page drops it
# Elements per rendered character, for the coarse estimate used when no export
# exists. The two committed sheets measure 60 and 29 — a factor of two apart on
# the same design, because a plotted sheet's size is not a function of its text
# alone. So the estimate takes the pessimistic rate and is only ever allowed to
# WARN, and only when it is half again over budget. The trustworthy number
# comes from a real export, which is why this shells out to `kicad-cli` when it
# can rather than guessing.
ELEMENTS_PER_CHAR = 60
DECAP_MM = 25.4
ANNOT_ROW_MM = 25.4
AUTONET_PINS = 4
FILL_MAX = 0.80
FILL_MIN = 0.15

PAPER = {  # width, height in mm, landscape
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297),
    "A4": (297, 210), "A5": (210, 148),
    "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
    "D": (863.6, 558.8), "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9),
    "USLedger": (431.8, 279.4),
}

GND_RE = re.compile(r"^(GND|AGND|DGND|PGND|GNDA|GNDD|GNDREF|EARTH|VSS\w*|0V)$", re.I)
AUTONET_RE = re.compile(r"^(Net-\(|N\$\d+$|unnamed)", re.I)
CAP_VALUE_RE = re.compile(r"^\s*([\d.]+)\s*([pnumµ]?)\s*F?\s*$", re.I)
MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0}

CODES = [
    "SCH-GRID", "SCH-DIAG", "SCH-DENSITY", "SCH-TITLE", "SCH-REVSKEW",
    "SCH-TEXTSIZE", "SCH-SHEETPIN", "SCH-PWRDIR", "SCH-AUTONET", "SCH-DECAP",
    "SCH-OVERLAP", "SCH-ANNOT", "SCH-FLOW", "SCH-PLAN",
]


def finding(code, severity, what, sheet=None, where=None, extent=None,
            refs=None, **extra) -> dict:
    f = {"code": code, "severity": severity, "what": what}
    if sheet is not None:
        f["sheet"] = sheet
    if where is not None:
        f["where"] = {"x": round(where[0], 4), "y": round(where[1], 4)}
    if extent is not None:
        f["extent"] = {k: round(v, 4) for k, v in
                       zip("xywh", extent)}
    if refs:
        f["refs"] = list(refs)
    f.update(extra)
    return f


def ongrid(v: float, grid: float = GRID) -> bool:
    return abs(v / grid - round(v / grid)) < TOL


# --------------------------------------------------------------------------
# Library geometry
# --------------------------------------------------------------------------
class Lib:
    """Pin and body geometry for the `lib_symbols` cached inside a sheet.

    KiCad stores a placed symbol as a `lib_id` and an `(at x y rot)`; the pins
    live only in the library block, in a coordinate system with **+Y up**
    while the sheet has **+Y down**. Every check that touches a pin depends on
    getting that flip and the rotation right, so `tests/smoke.sh` asserts that
    every computed pin lands on the grid before believing any of them.
    """

    def __init__(self, doc):
        self.syms = {}
        for s in sx.find_all(sx.find(doc, "lib_symbols") or ["lib_symbols"], "symbol"):
            if len(s) > 1 and isinstance(s[1], str):
                self.syms[s[1]] = s

    def _subs(self, lib_id, unit, style=1):
        """Sub-symbols of a library entry for one unit and one body style.

        The suffix is `NAME_<unit>_<bodystyle>`. Unit 0 is the part of the
        drawing shared by every unit; body style 2 is the De Morgan
        alternative, drawn only when the instance asks for it with
        `(convert 2)`. Including both styles double-counts every pin — a
        PIC16F54 reads as 36 pins instead of 18, which quietly doubles the
        density estimate and puts phantom pins into every geometric check.
        """
        s = self.syms.get(lib_id)
        if s is None:
            return []
        out = []
        for sub in sx.find_all(s, "symbol"):
            parts = str(sub[1]).rsplit("_", 2)
            try:
                u, st = int(float(parts[-2])), int(float(parts[-1]))
            except (ValueError, IndexError):
                u, st = 0, 1
            if u in (0, int(float(unit))) and st in (0, int(style)):
                out.append(sub)
        return out

    def pins(self, lib_id, unit, style=1) -> list[dict]:
        out = []
        for sub in self._subs(lib_id, unit, style):
            for p in sx.find_all(sub, "pin"):
                a = sx.at(p)
                if a is None:
                    continue
                out.append({
                    "x": a[0], "y": a[1], "angle": a[2],
                    "type": p[1] if len(p) > 1 and isinstance(p[1], str) else "passive",
                    "number": str(sx.attr(p, "number", 1, "")),
                    "name": str(sx.attr(p, "name", 1, "")),
                    "length": float(sx.attr(p, "length", 1, 0.0) or 0.0),
                })
        return out

    def body(self, lib_id, unit, style=1) -> tuple[float, float, float, float] | None:
        """Bounding box of the drawn body in library coordinates."""
        xs, ys = [], []
        for sub in self._subs(lib_id, unit, style):
            for r in sx.find_all(sub, "rectangle"):
                for k in ("start", "end"):
                    n = sx.find(r, k)
                    if n and len(n) >= 3:
                        xs.append(float(n[1])); ys.append(float(n[2]))
            for poly in sx.find_all(sub, "polyline") + sx.find_all(sub, "bezier"):
                for xy in sx.find_all(sx.find(poly, "pts") or ["pts"], "xy"):
                    xs.append(float(xy[1])); ys.append(float(xy[2]))
            for c in sx.find_all(sub, "circle"):
                n = sx.find(c, "center"); r = sx.attr(c, "radius", 1, 0.0)
                if n and len(n) >= 3:
                    xs += [float(n[1]) - r, float(n[1]) + r]
                    ys += [float(n[2]) - r, float(n[2]) + r]
            for a in sx.find_all(sub, "arc"):
                for k in ("start", "mid", "end"):
                    n = sx.find(a, k)
                    if n and len(n) >= 3:
                        xs.append(float(n[1])); ys.append(float(n[2]))
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    def pin_text_hidden(self, lib_id) -> tuple[bool, bool]:
        """(names hidden, numbers hidden) for a library symbol.

        `(pin_names (offset 0.254) hide)` in KiCad 6/7, `(hide yes)` in 8+.
        A part that hides both — a resistor, a capacitor — contributes no pin
        text at all, and counting it as if it did overstates every sheet of
        passives.
        """
        s = self.syms.get(lib_id)
        if s is None:
            return (False, False)
        return (sx.is_hidden_flag(sx.find(s, "pin_names")),
                sx.is_hidden_flag(sx.find(s, "pin_numbers")))

    def is_power(self, lib_id) -> bool:
        s = self.syms.get(lib_id)
        return bool(s is not None and sx.find(s, "power") is not None)


def place(lx: float, ly: float, ox: float, oy: float, rot: float,
          mx: bool, my: bool) -> tuple[float, float]:
    """Library coordinates -> sheet coordinates.

    Mirror first, then rotate, then flip Y: the composition KiCad itself uses.
    Verified empirically against the committed `pic_programmer` demo, where it
    puts all 182 pins exactly on the 1.27 mm grid and 71% of them on a wire
    endpoint, junction or label. Any other sign convention scatters them.
    """
    if mx:
        ly = -ly
    if my:
        lx = -lx
    r = math.radians(rot)
    cos_r, sin_r = math.cos(r), math.sin(r)
    return (ox + lx * cos_r - ly * sin_r,
            oy - (lx * sin_r + ly * cos_r))


# --------------------------------------------------------------------------
# Sheet model
# --------------------------------------------------------------------------
class Sheet:
    def __init__(self, path: str, doc, name: str, page: str, instance: str):
        self.path = path
        self.doc = doc
        self.name = name or os.path.basename(path)
        self.page = page
        self.instance = instance          # hierarchical path, "/" for the root
        self.lib = Lib(doc)
        self.symbols: list[dict] = []
        self.segments: list[tuple] = []   # (x1,y1,x2,y2,kind)
        self.labels: list[dict] = []
        self.junctions: list[tuple] = []
        self.no_connects: list[tuple] = []
        self.child_sheets: list[dict] = []
        self._build()

    # -- geometry -----------------------------------------------------------
    def _build(self):
        d = self.doc
        for s in sx.find_all(d, "symbol"):
            a = sx.at(s)
            if a is None:
                continue
            lib_id = str(sx.attr(s, "lib_id", 1, ""))
            unit = sx.attr(s, "unit", 1, 1)
            style = sx.attr(s, "convert", 1, 1) or 1
            mir = sx.find(s, "mirror")
            mx = bool(mir and "x" in mir[1:])
            my = bool(mir and "y" in mir[1:])
            p = sx.props(s)
            ref = str(p.get("Reference", ""))
            pins = []
            for lp in self.lib.pins(lib_id, unit, style):
                px, py = place(lp["x"], lp["y"], a[0], a[1], a[2], mx, my)
                pins.append({**lp, "sx": px, "sy": py})
            bb = self.lib.body(lib_id, unit, style)
            box = None
            if bb:
                cs = [place(bb[0], bb[1], a[0], a[1], a[2], mx, my),
                      place(bb[2], bb[1], a[0], a[1], a[2], mx, my),
                      place(bb[0], bb[3], a[0], a[1], a[2], mx, my),
                      place(bb[2], bb[3], a[0], a[1], a[2], mx, my)]
                box = (min(c[0] for c in cs), min(c[1] for c in cs),
                       max(c[0] for c in cs), max(c[1] for c in cs))
            self.symbols.append({
                "node": s, "lib_id": lib_id, "ref": ref,
                "value": str(p.get("Value", "")), "props": p,
                "x": a[0], "y": a[1], "rot": a[2], "unit": unit, "style": style,
                "mx": mx, "my": my, "pins": pins, "box": box,
                "power": self.lib.is_power(lib_id) or ref.startswith("#PWR"),
                "flag": ref.startswith("#FLG") or "PWR_FLAG" in lib_id.upper(),
            })

        for kind in ("wire", "bus"):
            for w in sx.find_all(d, kind):
                pts = sx.find_all(sx.find(w, "pts") or ["pts"], "xy")
                for i in range(len(pts) - 1):
                    self.segments.append((float(pts[i][1]), float(pts[i][2]),
                                          float(pts[i + 1][1]), float(pts[i + 1][2]),
                                          kind))

        for kind in ("label", "global_label", "hierarchical_label"):
            for n in sx.find_all(d, kind):
                a = sx.at(n)
                if a is None:
                    continue
                self.labels.append({
                    "node": n, "kind": kind,
                    "text": str(n[1]) if len(n) > 1 else "",
                    "x": a[0], "y": a[1], "rot": a[2],
                    "shape": str(sx.attr(n, "shape", 1, "")),
                })

        for n in sx.find_all(d, "junction"):
            a = sx.at(n)
            if a:
                self.junctions.append((a[0], a[1]))
        for n in sx.find_all(d, "no_connect"):
            a = sx.at(n)
            if a:
                self.no_connects.append((a[0], a[1]))

        for sh in sx.find_all(d, "sheet"):
            a = sx.at(sh)
            size = sx.find(sh, "size")
            p = sx.props(sh)
            pins = []
            for pn in sx.find_all(sh, "pin"):
                pa = sx.at(pn)
                pins.append({
                    "name": str(pn[1]) if len(pn) > 1 else "",
                    "dir": str(pn[2]) if len(pn) > 2 and isinstance(pn[2], str) else "",
                    "x": pa[0] if pa else 0.0, "y": pa[1] if pa else 0.0,
                    "node": pn,
                })
            self.child_sheets.append({
                "node": sh,
                "name": str(p.get("Sheetname") or p.get("Sheet name") or ""),
                "file": str(p.get("Sheetfile") or p.get("Sheet file") or ""),
                "x": a[0] if a else 0.0, "y": a[1] if a else 0.0,
                "w": float(size[1]) if size and len(size) > 2 else 0.0,
                "h": float(size[2]) if size and len(size) > 2 else 0.0,
                "pins": pins,
            })

    # -- page ---------------------------------------------------------------
    @property
    def paper(self) -> tuple[str, float, float]:
        p = sx.find(self.doc, "paper")
        if p is None or len(p) < 2:
            return ("A4", *PAPER["A4"])
        name = str(p[1])
        if name == "User" and len(p) >= 4:
            return ("User", float(p[2]), float(p[3]))
        w, h = PAPER.get(name, PAPER["A4"])
        if len(p) > 2 and str(p[2]) == "portrait":
            w, h = h, w
        return (name, w, h)

    @property
    def title_block(self) -> dict:
        tb = sx.find(self.doc, "title_block")
        if tb is None:
            return {}
        out = {}
        for key in ("title", "date", "rev", "company"):
            n = sx.find(tb, key)
            out[key] = str(n[1]) if n and len(n) > 1 else ""
        return out

    def used_bbox(self):
        xs, ys = [], []
        for s in self.symbols:
            if s["box"]:
                xs += [s["box"][0], s["box"][2]]
                ys += [s["box"][1], s["box"][3]]
            else:
                xs.append(s["x"]); ys.append(s["y"])
        for x1, y1, x2, y2, _ in self.segments:
            xs += [x1, x2]; ys += [y1, y2]
        for c in self.child_sheets:
            xs += [c["x"], c["x"] + c["w"]]; ys += [c["y"], c["y"] + c["h"]]
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    def visible_text(self) -> list[tuple[str, float, object]]:
        """(string, size, node) for everything a plotter will draw glyphs for.

        Pin names and numbers are in here because they are most of it. A
        14-pin logic part contributes two strings from its properties and
        twenty-eight from its pins, and leaving them out under-counts a dense
        sheet by about a third — which is the difference between a sheet the
        review page can embed and one it silently drops.
        """
        out = []
        for s in self.symbols:
            hide_names, hide_nums = self.lib.pin_text_hidden(s["lib_id"])
            for p in s["pins"]:
                if not hide_nums and p["number"]:
                    out.append((str(p["number"]), TEXT_SIZE, s["node"]))
                if not hide_names and p["name"] and p["name"] != "~":
                    out.append((str(p["name"]), TEXT_SIZE, s["node"]))
            for key in ("Reference", "Value"):
                pn = sx.prop_node(s["node"], key)
                if pn is None or sx.is_hidden(pn):
                    continue
                out.append((str(s["props"].get(key, "")),
                            sx.text_size(pn, TEXT_SIZE) or TEXT_SIZE, pn))
        for lb in self.labels:
            if not sx.is_hidden(lb["node"]):
                out.append((lb["text"], sx.text_size(lb["node"], TEXT_SIZE) or TEXT_SIZE,
                            lb["node"]))
        for t in sx.find_all(self.doc, "text"):
            if not sx.is_hidden(t):
                out.append((str(t[1]) if len(t) > 1 else "",
                            sx.text_size(t, TEXT_SIZE) or TEXT_SIZE, t))
        for c in self.child_sheets:
            for key in ("Sheetname", "Sheetfile", "Sheet name", "Sheet file"):
                pn = sx.prop_node(c["node"], key)
                if pn is not None and not sx.is_hidden(pn):
                    out.append((str(pn[2]) if len(pn) > 2 else "",
                                sx.text_size(pn, TEXT_SIZE) or TEXT_SIZE, pn))
            for p in c["pins"]:
                out.append((p["name"], sx.text_size(p["node"], TEXT_SIZE) or TEXT_SIZE,
                            p["node"]))
        return out


def load_hierarchy(root_path: str) -> list[Sheet]:
    """Every sheet reachable from the root, parsed once, cycle-guarded."""
    root_doc = sx.parse_file(root_path)
    pages = {}
    si = sx.find(root_doc, "sheet_instances")
    if si:
        for p in sx.find_all(si, "path"):
            if len(p) > 1:
                pg = sx.find(p, "page")
                pages[str(p[1])] = str(pg[1]) if pg and len(pg) > 1 else ""

    sheets: list[Sheet] = []
    seen: set[str] = set()

    def visit(path: str, name: str, instance: str, depth: int):
        real = os.path.realpath(path)
        if real in seen or depth > 12:
            return
        seen.add(real)
        doc = root_doc if depth == 0 else sx.parse_file(path)
        page = pages.get(instance, str(len(sheets) + 1))
        sh = Sheet(os.path.relpath(path), doc, name, page, instance)
        sheets.append(sh)
        base = os.path.dirname(os.path.abspath(path))
        for child in sh.child_sheets:
            if not child["file"]:
                continue
            cpath = os.path.normpath(os.path.join(base, child["file"]))
            if os.path.exists(cpath):
                visit(cpath, child["name"], instance.rstrip("/") + "/" + child["name"],
                      depth + 1)

    visit(root_path, os.path.splitext(os.path.basename(root_path))[0], "/", 0)
    return sheets


# --------------------------------------------------------------------------
# Connectivity — enough of it for the naming and decoupling checks
# --------------------------------------------------------------------------
def _q(x, y):
    return (round(x, 3), round(y, 3))


def _on_segment(px, py, x1, y1, x2, y2) -> bool:
    if min(x1, x2) - TOL > px or px > max(x1, x2) + TOL:
        return False
    if min(y1, y2) - TOL > py or py > max(y1, y2) + TOL:
        return False
    cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    return abs(cross) < 1e-3


def build_nets(sheet: Sheet) -> list[dict]:
    """Union-find over wire segments, then attach pins and labels.

    Deliberately sheet-local: the checks that use it — naming and decoupling
    proximity — are about what one sheet looks like. Cross-sheet connectivity
    is `kicad-cli sch export netlist`'s job and is not re-derived here.
    """
    parent: dict = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for x1, y1, x2, y2, _ in sheet.segments:
        union(_q(x1, y1), _q(x2, y2))
    for jx, jy in sheet.junctions:
        for x1, y1, x2, y2, _ in sheet.segments:
            if _on_segment(jx, jy, x1, y1, x2, y2):
                union(_q(jx, jy), _q(x1, y1))

    members: dict = defaultdict(lambda: {"pins": [], "labels": [], "pts": set()})

    def attach(px, py):
        """Root of whatever this point touches, creating its own node if free."""
        pt = _q(px, py)
        for x1, y1, x2, y2, _ in sheet.segments:
            if _on_segment(px, py, x1, y1, x2, y2):
                union(pt, _q(x1, y1))
                break
        return find(pt)

    for s in sheet.symbols:
        for p in s["pins"]:
            root = attach(p["sx"], p["sy"])
            members[root]["pins"].append((s, p))
            members[root]["pts"].add(_q(p["sx"], p["sy"]))
    for lb in sheet.labels:
        root = attach(lb["x"], lb["y"])
        members[root]["labels"].append(lb)
        members[root]["pts"].add(_q(lb["x"], lb["y"]))
    for c in sheet.child_sheets:
        for p in c["pins"]:
            root = attach(p["x"], p["y"])
            members[root]["labels"].append({"kind": "sheet_pin", "text": p["name"],
                                            "x": p["x"], "y": p["y"], "rot": 0.0,
                                            "node": p["node"], "shape": p["dir"]})

    nets = []
    for root, m in members.items():
        names = [lb["text"] for lb in m["labels"] if lb["text"]]
        power = [s["value"] for s, _ in m["pins"] if s["power"]]
        nets.append({
            "name": names[0] if names else (power[0] if power else ""),
            "names": names, "power_names": power,
            "pins": m["pins"], "labels": m["labels"], "pts": m["pts"],
        })
    return nets


def cap_farads(value: str):
    m = CAP_VALUE_RE.match(value.replace("Ω", "").strip())
    if not m:
        # 4u7 / 100n style
        m2 = re.match(r"^\s*(\d+)([pnumµ])(\d+)\s*F?\s*$", value.strip(), re.I)
        if not m2:
            return None
        return float(f"{m2.group(1)}.{m2.group(3)}") * MULT.get(m2.group(2).lower(), 1.0)
    return float(m.group(1)) * MULT.get(m.group(2).lower(), 1.0)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_grid(sh: Sheet, cfg) -> list[dict]:
    """Everything electrical on the grid.

    Property *text* positions are excluded on purpose: KiCad's autoplacer puts
    a reference at (27.3812, 91.5416) on a design that is otherwise perfectly
    on-grid, and grid-checking those emits about forty errors on a finished
    board. A gate that fires on clean work is a gate people switch off.
    """
    out = []
    g = cfg.grid
    for s in sh.symbols:
        if not (ongrid(s["x"], g) and ongrid(s["y"], g)):
            out.append(finding("SCH-GRID", "ERROR",
                               f"{s['ref'] or s['lib_id']} placed at "
                               f"({s['x']:.4f}, {s['y']:.4f}) — off the "
                               f"{g} mm grid",
                               sh.name, (s["x"], s["y"]), refs=[s["ref"]]))
        for p in s["pins"]:
            if not (ongrid(p["sx"], g) and ongrid(p["sy"], g)):
                out.append(finding("SCH-GRID", "ERROR",
                                   f"{s['ref']} pin {p['number']} lands at "
                                   f"({p['sx']:.4f}, {p['sy']:.4f}) — off grid, "
                                   f"so a wire drawn to it will not connect",
                                   sh.name, (p["sx"], p["sy"]), refs=[s["ref"]]))
    for x1, y1, x2, y2, kind in sh.segments:
        for (px, py) in ((x1, y1), (x2, y2)):
            if not (ongrid(px, g) and ongrid(py, g)):
                out.append(finding("SCH-GRID", "ERROR",
                                   f"{kind} endpoint at ({px:.4f}, {py:.4f}) "
                                   f"is off the {g} mm grid",
                                   sh.name, (px, py)))
    for lb in sh.labels:
        if not (ongrid(lb["x"], g) and ongrid(lb["y"], g)):
            out.append(finding("SCH-GRID", "ERROR",
                               f"label {lb['text']!r} at ({lb['x']:.4f}, "
                               f"{lb['y']:.4f}) is off grid",
                               sh.name, (lb["x"], lb["y"])))
    for c in sh.child_sheets:
        for p in c["pins"]:
            if not (ongrid(p["x"], g) and ongrid(p["y"], g)):
                out.append(finding("SCH-GRID", "ERROR",
                                   f"sheet pin {p['name']!r} is off grid",
                                   sh.name, (p["x"], p["y"])))
    return out


def check_diag(sh: Sheet, cfg) -> list[dict]:
    out = []
    for x1, y1, x2, y2, kind in sh.segments:
        if abs(x1 - x2) > TOL and abs(y1 - y2) > TOL:
            out.append(finding("SCH-DIAG", "ERROR",
                               f"diagonal {kind} from ({x1:.2f}, {y1:.2f}) to "
                               f"({x2:.2f}, {y2:.2f})",
                               sh.name, ((x1 + x2) / 2, (y1 + y2) / 2),
                               extent=(min(x1, x2), min(y1, y2),
                                       abs(x2 - x1), abs(y2 - y1))))
    return out


def check_density(sh: Sheet, cfg, measured: int | None) -> list[dict]:
    """How big this sheet will be once a plotter turns text into outlines.

    KiCad's SVG exporter writes one path per line segment, glyph strokes
    included, so a single A4 sheet can be three megabytes and 61,681 elements —
    far past what `exports.md` says the review page can inline. A sheet over
    the budget is not a sheet with a rendering problem; it is a sheet with too
    much on it, and the fix is to split it.
    """
    out = []
    chars = sum(len(t) for t, _, _ in sh.visible_text())
    est = chars * ELEMENTS_PER_CHAR
    n = measured if measured is not None else est
    src = "measured" if measured is not None else "estimated, +/-2x"

    if measured is not None:
        if n >= cfg.budget:
            out.append(finding("SCH-DENSITY", "ERROR",
                               f"{n:,} SVG elements ({src}) against a "
                               f"{cfg.budget:,} budget — {n / cfg.budget:.1f}x over. "
                               f"The review page cannot embed this sheet; split it.",
                               sh.name, elements=n, budget=cfg.budget, source=src))
        elif n >= 0.7 * cfg.budget:
            out.append(finding("SCH-DENSITY", "WARN",
                               f"{n:,} SVG elements ({src}) — "
                               f"{100 * n / cfg.budget:.0f}% of the review-page "
                               f"budget. One more block splits it.",
                               sh.name, elements=n, budget=cfg.budget, source=src))
    elif est >= 1.5 * cfg.budget:
        # Never an ERROR: the estimate is only good to a factor of two, and a
        # gate that fails on a guess is a gate someone turns off.
        out.append(finding("SCH-DENSITY", "WARN",
                           f"roughly {est:,} SVG elements ({src}) against a "
                           f"{cfg.budget:,} budget. Export the sheet and re-run "
                           f"with --svg-measure for a real number.",
                           sh.name, elements=est, budget=cfg.budget, source=src))

    bb = sh.used_bbox()
    _, pw, ph = sh.paper
    if bb and pw and ph:
        fill = ((bb[2] - bb[0]) * (bb[3] - bb[1])) / (pw * ph)
        if fill > FILL_MAX:
            out.append(finding("SCH-DENSITY", "WARN",
                               f"drawing fills {100 * fill:.0f}% of the page — "
                               f"no margin left to add anything or to read it",
                               sh.name, fill=round(fill, 3)))
        elif fill < FILL_MIN and len(sh.symbols) > 4:
            out.append(finding("SCH-DENSITY", "WARN",
                               f"drawing uses {100 * fill:.0f}% of the page — "
                               f"a smaller sheet reads better than a mostly empty one",
                               sh.name, fill=round(fill, 3)))
    return out


def check_title(sheets: list[Sheet], cfg) -> list[dict]:
    out = []
    revs = {}
    for sh in sheets:
        tb = sh.title_block
        if not tb:
            out.append(finding("SCH-TITLE", "ERROR",
                               "no title block at all — a printed sheet with no "
                               "name, revision or date is not a document",
                               sh.name))
            continue
        for key, sev in (("title", "ERROR"), ("rev", "ERROR"),
                         ("date", "WARN"), ("company", "WARN")):
            if not tb.get(key):
                out.append(finding("SCH-TITLE", sev,
                                   f"title block has no {key}", sh.name))
        if tb.get("rev"):
            revs.setdefault(tb["rev"], []).append(sh.name)
    if len(revs) > 1:
        listing = "; ".join(f"rev {r}: {', '.join(n)}" for r, n in sorted(revs.items()))
        out.append(finding("SCH-REVSKEW", "WARN",
                           f"sheets are at different revisions ({listing}) — "
                           f"a reviewer cannot tell which drawing they agreed to"))
    return out


def check_textsize(sh: Sheet, cfg) -> list[dict]:
    sizes = Counter()
    for text, size, _node in sh.visible_text():
        if text:
            sizes[round(size, 3)] += 1
    allowed = {round(cfg.text_size, 3)} | {round(a, 3) for a in cfg.text_allow}
    out = []
    for size, n in sorted(sizes.items(), key=lambda kv: -kv[1]):
        if size not in allowed:
            out.append(finding("SCH-TEXTSIZE", "WARN",
                               f"{n} text item(s) at {size} mm — the house size is "
                               f"{cfg.text_size} mm "
                               f"({', '.join(str(a) for a in cfg.text_allow)} allowed "
                               f"for headings)",
                               sh.name, count=n, size=size))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def check_sheetpin(sheets: list[Sheet], cfg) -> list[dict]:
    by_file = {os.path.realpath(sh.path): sh for sh in sheets}
    out = []
    for sh in sheets:
        base = os.path.dirname(os.path.abspath(sh.path))
        for c in sh.child_sheets:
            if not c["file"]:
                continue
            child = by_file.get(os.path.realpath(os.path.join(base, c["file"])))
            if child is None:
                out.append(finding("SCH-SHEETPIN", "ERROR",
                                   f"sheet {c['name']!r} points at {c['file']!r}, "
                                   f"which is not there",
                                   sh.name, (c["x"], c["y"])))
                continue
            hier = {lb["text"]: lb for lb in child.labels
                    if lb["kind"] == "hierarchical_label"}
            pins = {p["name"]: p for p in c["pins"]}
            for name, p in pins.items():
                if name in hier:
                    continue
                near = [h for h in hier if _norm(h) == _norm(name)]
                hint = f" — did you mean {near[0]!r}?" if near else ""
                out.append(finding("SCH-SHEETPIN", "ERROR",
                                   f"sheet {c['name']!r} has a pin {name!r} with no "
                                   f"matching hierarchical label inside{hint}",
                                   sh.name, (p["x"], p["y"]), refs=[c["name"]]))
            for name, lb in hier.items():
                if name in pins:
                    continue
                near = [p for p in pins if _norm(p) == _norm(name)]
                hint = f" — did you mean {near[0]!r}?" if near else ""
                out.append(finding("SCH-SHEETPIN", "ERROR",
                                   f"{child.name}: hierarchical label {name!r} is not "
                                   f"brought out as a pin on the parent sheet{hint}",
                                   child.name, (lb["x"], lb["y"])))
    return out


def check_pwrdir(sh: Sheet, cfg) -> list[dict]:
    """Rails drawn upward, grounds drawn downward.

    Not decoration. A reader scans a schematic for supply structure by
    silhouette before reading a single label, and a ground symbol pointing up
    breaks that read for every sheet it appears on.
    """
    out = []
    for s in sh.symbols:
        if not s["power"] or s["flag"] or not s["pins"]:
            continue
        bb = sh.lib.body(s["lib_id"], s["unit"], s["style"])
        if not bb:
            continue
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        bx, by = place(cx, cy, s["x"], s["y"], s["rot"], s["mx"], s["my"])
        pin = s["pins"][0]
        dx, dy = bx - pin["sx"], by - pin["sy"]
        if abs(dy) <= abs(dx):
            out.append(finding("SCH-PWRDIR", "WARN",
                               f"{s['value'] or s['ref']} is drawn sideways — power "
                               f"symbols read vertically",
                               sh.name, (s["x"], s["y"]), refs=[s["ref"]]))
            continue
        is_gnd = bool(GND_RE.match(s["value"].strip()))
        # sheet Y grows downward: a body below its pin has dy > 0
        if is_gnd and dy < 0:
            out.append(finding("SCH-PWRDIR", "WARN",
                               f"{s['value']} is drawn pointing up — grounds go down",
                               sh.name, (s["x"], s["y"]), refs=[s["ref"]]))
        elif not is_gnd and dy > 0:
            out.append(finding("SCH-PWRDIR", "WARN",
                               f"{s['value']} is drawn pointing down — rails go up",
                               sh.name, (s["x"], s["y"]), refs=[s["ref"]]))
    return out


def check_autonet(sh: Sheet, nets, cfg) -> list[dict]:
    out = []
    for net in nets:
        pins = [p for p in net["pins"] if not p[0]["power"]]
        if len(pins) < cfg.autonet_pins:
            continue
        if net["power_names"]:
            continue
        named = [n for n in net["names"] if n and not AUTONET_RE.match(n)]
        if named:
            continue
        refs = sorted({s["ref"] for s, _ in net["pins"] if s["ref"]})
        auto = next((n for n in net["names"] if n), "")
        where = sorted(net["pts"])[0] if net["pts"] else None
        out.append(finding(
            "SCH-AUTONET", "WARN" if not cfg.strict else "ERROR",
            (f"net named {auto!r}" if auto else "unnamed net") +
            f" carries {len(pins)} pins ({', '.join(refs[:6])}"
            f"{'…' if len(refs) > 6 else ''}) — name it after what it carries, "
            f"not after where it happens to start",
            sh.name, where, refs=refs))
    return out


def check_decap(sh: Sheet, nets, cfg) -> list[dict]:
    """A decoupling capacitor drawn beside the pin it serves.

    This is a drawing rule, not a layout rule — `pcb-lint` measures the copper.
    But a cap drawn on the other side of the sheet from its IC is a cap nobody
    reviewing the schematic will connect to that IC, and it is usually the same
    cap that ends up 12 mm away on the board.
    """
    out = []
    pin_owner = {}
    for net in nets:
        for s, p in net["pins"]:
            pin_owner.setdefault(id(s), []).append((net, p))

    for s in sh.symbols:
        if not s["ref"].startswith("C") or s["power"]:
            continue
        f = cap_farads(s["value"])
        if f is None or not (0 < f <= 1e-6):
            continue
        best = None
        for net, _p in pin_owner.get(id(s), []):
            for other, op in net["pins"]:
                if other is s or other["power"]:
                    continue
                if len(other["pins"]) < 6 and not other["ref"].startswith(("U", "IC")):
                    continue
                d = math.hypot(other["x"] - s["x"], other["y"] - s["y"])
                if best is None or d < best[0]:
                    best = (d, other, op)
        if best is None:
            continue
        d, ic, op = best
        if d > 2 * cfg.decap_mm:
            sev = "ERROR"
        elif d > cfg.decap_mm:
            sev = "WARN"
        else:
            continue
        out.append(finding("SCH-DECAP", sev,
                           f"{s['ref']} ({s['value']}) is drawn {d:.0f} mm from "
                           f"{ic['ref']} pin {op['number']}, the pin it decouples — "
                           f"draw it beside the pin",
                           sh.name, (s["x"], s["y"]),
                           refs=[s["ref"], ic["ref"]], distance_mm=round(d, 1)))
    return out


def check_overlap(sh: Sheet, cfg) -> list[dict]:
    out = []
    boxes = [(s, s["box"]) for s in sh.symbols if s["box"]]
    for i in range(len(boxes)):
        si, bi = boxes[i]
        for j in range(i + 1, len(boxes)):
            sj, bj = boxes[j]
            ox = min(bi[2], bj[2]) - max(bi[0], bj[0])
            oy = min(bi[3], bj[3]) - max(bi[1], bj[1])
            if ox <= 0 or oy <= 0:
                continue
            area = ox * oy
            if area < 0.5:
                continue
            if si["power"] and sj["power"]:
                continue
            out.append(finding("SCH-OVERLAP", "ERROR",
                               f"{si['ref'] or si['lib_id']} and "
                               f"{sj['ref'] or sj['lib_id']} overlap by "
                               f"{area:.1f} mm²",
                               sh.name,
                               ((max(bi[0], bj[0]) + min(bi[2], bj[2])) / 2,
                                (max(bi[1], bj[1]) + min(bi[3], bj[3])) / 2),
                               extent=(max(bi[0], bj[0]), max(bi[1], bj[1]), ox, oy),
                               refs=[si["ref"], sj["ref"]], area_mm2=round(area, 2)))
    return out


def check_annot(sh: Sheet, cfg) -> list[dict]:
    """Designators counting the way the eye moves.

    R1 top-left and R2 bottom-right is not wrong, it is just unfindable. On a
    board review someone is holding a BOM line and looking for R47.
    """
    out = []
    groups = defaultdict(list)
    for s in sh.symbols:
        m = re.match(r"^([A-Za-z]+)(\d+)$", s["ref"])
        if not m or s["ref"].startswith("#"):
            continue
        groups[m.group(1)].append((int(m.group(2)), s))
    for prefix, items in sorted(groups.items()):
        if len(items) < 4:
            continue
        reading = sorted(items, key=lambda it: (round(it[1]["y"] / cfg.annot_row_mm),
                                                it[1]["x"]))
        order = [n for n, _ in reading]
        inv = sum(1 for a in range(len(order)) for b in range(a + 1, len(order))
                  if order[a] > order[b])
        pairs = len(order) * (len(order) - 1) / 2
        if pairs and inv / pairs > 0.2:
            worst = ", ".join(f"{prefix}{n}" for n in order[:6])
            out.append(finding("SCH-ANNOT", "WARN",
                               f"{prefix}* is not annotated in reading order "
                               f"({100 * inv / pairs:.0f}% of pairs inverted; reading "
                               f"order starts {worst}) — re-annotate",
                               sh.name, inversion=round(inv / pairs, 3)))
    return out


def check_flow(sh: Sheet, cfg) -> list[dict]:
    """Inputs on the left, outputs on the right.

    A heuristic, and reported as a number rather than a verdict. It never
    gates: a power sheet legitimately flows top to bottom and a sheet of
    connectors flows nowhere.
    """
    bb = sh.used_bbox()
    if not bb or bb[2] - bb[0] < 1:
        return []
    span = bb[2] - bb[0]
    ins, outs = [], []
    for lb in sh.labels:
        if lb["kind"] not in ("hierarchical_label", "global_label"):
            continue
        xn = (lb["x"] - bb[0]) / span
        if lb["shape"] in ("input",):
            ins.append(xn)
        elif lb["shape"] in ("output",):
            outs.append(xn)
    for c in sh.child_sheets:
        for p in c["pins"]:
            xn = (p["x"] - bb[0]) / span
            (ins if p["dir"] == "input" else outs if p["dir"] == "output"
             else []).append(xn) if p["dir"] in ("input", "output") else None
    if len(ins) < 2 or len(outs) < 2:
        return []
    flow = sum(outs) / len(outs) - sum(ins) / len(ins)
    if flow < 0.15:
        return [finding("SCH-FLOW", "WARN",
                        f"signal flow reads {flow:+.2f} (inputs at "
                        f"{sum(ins) / len(ins):.2f}, outputs at "
                        f"{sum(outs) / len(outs):.2f} across the sheet) — "
                        f"a reader expects inputs left, outputs right",
                        sh.name, flow=round(flow, 3))]
    return []


def check_plan(sheets: list[Sheet], plan_path: str, cfg) -> list[dict]:
    """Every block the human agreed to, on exactly one sheet.

    The architecture review is the last point where a missing rail is an edit
    rather than a respin, and this is what makes that agreement bind: a block
    in `block-diagram.yaml` that never reaches the schematic is a silently
    dropped decision.
    """
    try:
        import yaml
    except ImportError:
        return [finding("SCH-PLAN", "WARN", "pyyaml is not installed — "
                                            "cannot check the schematic against the block diagram")]
    try:
        with open(plan_path) as fh:
            spec = yaml.safe_load(fh) or {}
    except OSError as exc:
        return [finding("SCH-PLAN", "ERROR", f"cannot read {plan_path}: {exc}")]

    blocks = spec.get("blocks") or []
    if not blocks:
        return [finding("SCH-PLAN", "WARN", f"{plan_path} declares no blocks")]

    out = []
    for b in blocks:
        bid = str(b.get("id", ""))
        part = str(b.get("part", "") or "")
        name = str(b.get("name", "") or "")
        refs = [str(r) for r in (b.get("refs") or [])]
        hits, rule = [], ""
        for sh in sheets:
            for s in sh.symbols:
                if s["power"] or s["flag"]:
                    continue
                if refs and s["ref"] in refs:
                    hits.append((sh, s)); rule = "refs:"
                elif part and part.lower() in (s["value"] + " " +
                                               str(s["props"].get("Footprint", ""))).lower():
                    hits.append((sh, s)); rule = rule or "part:"
                elif bid and s["ref"].lower() == bid.lower():
                    hits.append((sh, s)); rule = rule or "id:"
                elif name and _norm(name) and _norm(name) in _norm(s["value"]):
                    hits.append((sh, s)); rule = rule or "name: (fuzzy)"
        pages = sorted({sh.name for sh, _ in hits})
        label = name or bid
        if not hits:
            out.append(finding("SCH-PLAN", "ERROR",
                               f"block {label!r} is in the agreed block diagram and "
                               f"on no sheet — it was dropped without a decision",
                               refs=refs, block=bid))
        elif len(pages) > 1:
            sev = "ERROR" if rule != "name: (fuzzy)" else "WARN"
            out.append(finding("SCH-PLAN", sev,
                               f"block {label!r} appears on {len(pages)} sheets "
                               f"({', '.join(pages)}) — matched by {rule}",
                               sheet=pages[0], refs=refs, block=bid))

    # A sheet carrying two unrelated functional groups is a sheet nobody can
    # name. Power is exempt: rails and their decoupling are everywhere.
    group_of = {}
    for b in blocks:
        g = b.get("group")
        if not g:
            kind = str(b.get("kind", ""))
            g = "power" if kind in ("regulator", "supply", "power", "battery",
                                    "ldo", "buck", "boost") else ""
        if g:
            group_of[str(b.get("id", ""))] = str(g)
    if group_of:
        for sh in sheets:
            seen = set()
            for s in sh.symbols:
                for bid, g in group_of.items():
                    if g != "power" and bid and s["ref"].lower() == bid.lower():
                        seen.add(g)
            if len(seen) > 1:
                out.append(finding("SCH-PLAN", "WARN",
                                   f"sheet carries blocks from {len(seen)} functional "
                                   f"groups ({', '.join(sorted(seen))}) — one sheet, "
                                   f"one job",
                                   sh.name))
    return out


# --------------------------------------------------------------------------
# SVG overlay — the findings, drawn on the sheet
# --------------------------------------------------------------------------
SEV_COLOUR = {"ERROR": "#d03b3b", "WARN": "#e08a1e"}
SEV_GLYPH = {"ERROR": "✕", "WARN": "!"}

SVG_STYLE = """
  .bg   { fill:#faf9f6 }
  .wire { stroke:#7a8899; stroke-width:.18; fill:none }
  .body { stroke:#9aa7b5; stroke-width:.18; fill:none }
  .lbl  { fill:#7a8899; font:1.6px sans-serif }
  .ref  { fill:#556; font:1.6px sans-serif }
  .cap  { fill:#333; font:2.2px sans-serif }
  .note { fill:#444; font:2.4px sans-serif }
  @media (prefers-color-scheme: dark) {
    .bg{fill:#14171a} .wire{stroke:#4d5b6b} .body{stroke:#5c6b7a}
    .lbl,.ref{fill:#8494a5} .cap,.note{fill:#c8d2dc}
  }
"""


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def overlay_svg(sh: Sheet, findings: list[dict]) -> str:
    """A drawing of the sheet with the findings marked on it.

    Deliberately *not* KiCad's export with markers on top. KiCad writes one
    path per glyph stroke — 61,681 elements for one A4 sheet — which blows the
    review page's budget and cannot be inlined. This draws wires as lines and
    symbols as boxes: about five hundred elements, it inlines anywhere, and it
    shows exactly the thing being reported, which the full plot does not.
    """
    _, pw, ph = sh.paper
    mine = [f for f in findings if f.get("sheet") == sh.name and "where" in f]
    margin = 60.0
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw + margin}mm" '
         f'height="{ph}mm" viewBox="0 0 {pw + margin} {ph}">',
         f"<style>{SVG_STYLE}</style>",
         f'<rect class="bg" x="0" y="0" width="{pw + margin}" height="{ph}"/>',
         f'<rect x="0" y="0" width="{pw}" height="{ph}" fill="none" '
         f'stroke="#c7c2b6" stroke-width=".3"/>']

    for x1, y1, x2, y2, _k in sh.segments:
        o.append(f'<line class="wire" x1="{x1:.2f}" y1="{y1:.2f}" '
                 f'x2="{x2:.2f}" y2="{y2:.2f}"/>')
    for s in sh.symbols:
        if s["box"]:
            b = s["box"]
            o.append(f'<rect class="body" x="{b[0]:.2f}" y="{b[1]:.2f}" '
                     f'width="{b[2] - b[0]:.2f}" height="{b[3] - b[1]:.2f}" rx=".5"/>')
        if s["ref"] and not s["ref"].startswith("#"):
            o.append(f'<text class="ref" x="{s["x"]:.2f}" y="{s["y"] - 0.6:.2f}">'
                     f'{esc(s["ref"])}</text>')
    for lb in sh.labels:
        o.append(f'<text class="lbl" x="{lb["x"]:.2f}" y="{lb["y"] - 0.5:.2f}">'
                 f'{esc(lb["text"])}</text>')
    for c in sh.child_sheets:
        o.append(f'<rect class="body" x="{c["x"]:.2f}" y="{c["y"]:.2f}" '
                 f'width="{c["w"]:.2f}" height="{c["h"]:.2f}"/>')
        o.append(f'<text class="ref" x="{c["x"] + 1:.2f}" y="{c["y"] + 4:.2f}">'
                 f'{esc(c["name"])}</text>')

    for i, f in enumerate(mine, 1):
        col = SEV_COLOUR.get(f["severity"], "#888")
        x, y = f["where"]["x"], f["where"]["y"]
        ext = f.get("extent")
        if ext and ext["w"] > 0.5 and ext["h"] > 0.5:
            o.append(f'<rect x="{ext["x"]:.2f}" y="{ext["y"]:.2f}" '
                     f'width="{ext["w"]:.2f}" height="{ext["h"]:.2f}" fill="none" '
                     f'stroke="{col}" stroke-width=".4" stroke-dasharray="1.2 .8"/>')
        o.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.4" fill="none" '
                 f'stroke="{col}" stroke-width=".5"/>'
                 f'<text x="{x:.2f}" y="{y + 0.8:.2f}" text-anchor="middle" '
                 f'fill="{col}" font="2.2px sans-serif" '
                 f'style="font:2.2px sans-serif">{i}</text>'
                 f'<title>{esc(f["severity"])}: {esc(f["what"])}</title>')

    y = 6.0
    o.append(f'<text class="note" x="{pw + 3:.1f}" y="{y:.1f}">'
             f'{esc(sh.name)} — {len(mine)} finding(s)</text>')
    for i, f in enumerate(mine, 1):
        y += 4.4
        if y > ph - 4:
            o.append(f'<text class="lbl" x="{pw + 3:.1f}" y="{y:.1f}">'
                     f'… {len(mine) - i + 1} more, see the report</text>')
            break
        col = SEV_COLOUR.get(f["severity"], "#888")
        txt = f["what"][:58] + ("…" if len(f["what"]) > 58 else "")
        o.append(f'<text x="{pw + 3:.1f}" y="{y:.1f}" fill="{col}" '
                 f'style="font:2.0px sans-serif">'
                 f'{SEV_GLYPH.get(f["severity"], "")} {i}. {esc(txt)}</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def report(sheets, findings, cfg) -> None:
    print(f"\nSchematic lint — {cfg.path}\n")
    syms = sum(len(s.symbols) for s in sheets)
    wires = sum(len(s.segments) for s in sheets)
    labels = sum(len(s.labels) for s in sheets)
    print(f"  {len(sheets)} sheet(s)   {syms} symbols   {wires} wire segments   "
          f"{labels} labels")
    for sh in sheets:
        name, pw, ph = sh.paper
        n = cfg.measured.get(sh.name)
        size = (f"{n:,} SVG elements (measured)" if n is not None else
                f"~{sum(len(t) for t, _, _ in sh.visible_text()) * ELEMENTS_PER_CHAR:,}"
                f" SVG elements (rough)")
        print(f"    sheet {sh.page or '?'}  {sh.name:<24} {name} "
              f"({pw:.0f}x{ph:.0f} mm)  {size}")
    print()

    if not findings:
        print("  Nothing to report. The drawing is readable.\n")
        return

    by_code = defaultdict(list)
    for f in findings:
        by_code[(f["severity"], f["code"])].append(f)
    for (sev, code) in sorted(by_code, key=lambda k: (k[0] != "ERROR", k[1])):
        items = by_code[(sev, code)]
        print(f"  {sev:<5}  {code} ({len(items)}):")
        for f in items[:12]:
            where = f.get("sheet", "")
            print(f"    - {where + ': ' if where else ''}{f['what']}")
        if len(items) > 12:
            print(f"    … and {len(items) - 12} more")
        print()

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    warns = len(findings) - errors
    print(f"  {errors} error(s), {warns} warning(s).")
    print("  --gate would " + ("fail." if errors else "pass.") + "\n")


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Readability and structure gate for a KiCad schematic.")
    ap.add_argument("path", nargs="?", help="root .kicad_sch (default: the one in hw/)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 on any ERROR")
    ap.add_argument("--strict", action="store_true",
                    help="promote the soft checks to ERROR")
    ap.add_argument("--only", default="", help="comma-separated codes to run")
    ap.add_argument("--ignore", default="", help="comma-separated codes to skip")
    ap.add_argument("--svg", metavar="DIR",
                    help="write one annotated overlay per sheet into DIR")
    ap.add_argument("--no-export", action="store_true",
                    help="do not shell out to kicad-cli to measure sheet size")
    ap.add_argument("--svg-measure", metavar="DIR",
                    help="a directory of kicad-cli sch export svg output; element "
                         "counts are then measured instead of estimated")
    ap.add_argument("--plan", metavar="YAML",
                    help="check every block in this block-diagram.yaml reaches a sheet")
    ap.add_argument("--grid", type=float, default=GRID)
    ap.add_argument("--text-size", type=float, default=TEXT_SIZE)
    ap.add_argument("--text-allow", default=",".join(str(a) for a in TEXT_ALLOW))
    ap.add_argument("--budget", type=int, default=SVG_ELEMENT_BUDGET)
    ap.add_argument("--decap-mm", type=float, default=DECAP_MM)
    ap.add_argument("--annot-row-mm", type=float, default=ANNOT_ROW_MM)
    ap.add_argument("--autonet-pins", type=int, default=AUTONET_PINS)
    cfg = ap.parse_args()
    cfg.text_allow = tuple(float(a) for a in cfg.text_allow.split(",") if a.strip())

    if not cfg.path:
        found = [os.path.join("hw", f) for f in sorted(os.listdir("hw"))
                 if f.endswith(".kicad_sch")] if os.path.isdir("hw") else []
        if len(found) != 1:
            print("sch-lint: name the root .kicad_sch "
                  f"({len(found)} found under hw/)", file=sys.stderr)
            return 2
        cfg.path = found[0]
    if not os.path.exists(cfg.path):
        print(f"sch-lint: no such file: {cfg.path}", file=sys.stderr)
        return 2

    try:
        sheets = load_hierarchy(cfg.path)
    except sx.SexprError as exc:
        print(f"sch-lint: cannot read {cfg.path}: {exc}", file=sys.stderr)
        return 2

    only = {c.strip().upper() for c in cfg.only.split(",") if c.strip()}
    skip = {c.strip().upper() for c in cfg.ignore.split(",") if c.strip()}

    def wanted(code):
        return (not only or code in only) and code not in skip

    measured = {}
    if (wanted("SCH-DENSITY") and not cfg.svg_measure and not cfg.no_export
            and shutil.which("kicad-cli")):
        # The real exporter is the only honest source for this number, and it
        # is right here. Failure is not fatal — the estimate takes over.
        tmp = tempfile.mkdtemp(prefix="sch-lint-")
        try:
            r = subprocess.run(
                ["kicad-cli", "sch", "export", "svg", cfg.path, "--output", tmp],
                capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                cfg.svg_measure = tmp
        except (OSError, subprocess.SubprocessError):
            pass
    if cfg.svg_measure and os.path.isdir(cfg.svg_measure):
        for fn in sorted(os.listdir(cfg.svg_measure)):
            if fn.endswith(".svg"):
                with open(os.path.join(cfg.svg_measure, fn),
                          encoding="utf-8", errors="replace") as fh:
                    measured[os.path.splitext(fn)[0]] = fh.read().count("<")

    cfg.measured = {}
    findings: list[dict] = []
    for sh in sheets:
        nets = None
        if wanted("SCH-AUTONET") or wanted("SCH-DECAP"):
            nets = build_nets(sh)
        if wanted("SCH-GRID"):
            findings += check_grid(sh, cfg)
        if wanted("SCH-DIAG"):
            findings += check_diag(sh, cfg)
        if wanted("SCH-DENSITY"):
            # kicad-cli names the root export after the project and every
            # child "<project>-<sheetname>.svg". Matching on a bare substring
            # gives the root's count to every sheet, which reads as a design
            # where every page is the same size — plausible, and wrong.
            stem = os.path.splitext(os.path.basename(cfg.path))[0]
            want = stem if sh.instance == "/" else f"{stem}-{sh.name}"
            m = measured.get(want)
            if m is None:
                m = next((v for k, v in measured.items()
                          if k.endswith("-" + sh.name)), None)
            if m is not None:
                cfg.measured[sh.name] = m
            findings += check_density(sh, cfg, m)
        if wanted("SCH-TEXTSIZE"):
            findings += check_textsize(sh, cfg)
        if wanted("SCH-PWRDIR"):
            findings += check_pwrdir(sh, cfg)
        if wanted("SCH-AUTONET"):
            findings += check_autonet(sh, nets, cfg)
        if wanted("SCH-DECAP"):
            findings += check_decap(sh, nets, cfg)
        if wanted("SCH-OVERLAP"):
            findings += check_overlap(sh, cfg)
        if wanted("SCH-ANNOT"):
            findings += check_annot(sh, cfg)
        if wanted("SCH-FLOW"):
            findings += check_flow(sh, cfg)
    if wanted("SCH-TITLE") or wanted("SCH-REVSKEW"):
        findings += [f for f in check_title(sheets, cfg) if wanted(f["code"])]
    if wanted("SCH-SHEETPIN"):
        findings += check_sheetpin(sheets, cfg)
    if cfg.plan and wanted("SCH-PLAN"):
        findings += check_plan(sheets, cfg.plan, cfg)

    if cfg.strict:
        for f in findings:
            if f["code"] in ("SCH-PWRDIR", "SCH-DECAP", "SCH-TEXTSIZE"):
                f["severity"] = "ERROR"

    if cfg.svg:
        os.makedirs(cfg.svg, exist_ok=True)
        for sh in sheets:
            slug = re.sub(r"[^A-Za-z0-9]+", "-", sh.name).strip("-").lower() or "sheet"
            out = os.path.join(cfg.svg, f"{sh.page or '0'}-{slug}.lint.svg")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(overlay_svg(sh, findings))
            if not cfg.json:
                print(f"wrote {out}")

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    if cfg.json:
        print(json.dumps({
            "file": cfg.path,
            "sheets": [{"name": s.name, "page": s.page, "path": s.path,
                        "symbols": len(s.symbols), "paper": s.paper[0]}
                       for s in sheets],
            "findings": findings,
            "errors": errors,
            "warnings": len(findings) - errors,
        }, indent=2))
    else:
        report(sheets, findings, cfg)

    return 1 if (cfg.gate and errors) else 0


if __name__ == "__main__":
    sys.exit(main())
