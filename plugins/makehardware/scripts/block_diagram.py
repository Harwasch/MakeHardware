#!/usr/bin/env python3
"""Validate an electrical block diagram and render it to draw.io and SVG.

The block diagram is the architecture agreement: which ICs exist, what feeds
them, and what talks to what. It is settled before schematic capture, because
finding out at layout time that a rail is 400 mA short is a respin.

    block-diagram                  # write hw/block-diagram.drawio + docs/design/block-diagram.svg
    block-diagram --check          # validate only; exit 1 on a real problem
    block-diagram --summary        # power budget per rail, no files written
    block-diagram --png            # also rasterise the SVG

One spec renders both outputs, so the editable file and the review image cannot
disagree. Generated layout is a starting point: positions you tidy by hand in
draw.io are read back and reused on the next run, keyed by block id.
"""
from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml

# ---------------------------------------------------------------------------
# Palette. Rails and buses carry the colour, because they are what the diagram
# is about; blocks stay neutral and are told apart by their kind label. Every
# coloured thing is also labelled, so nothing rides on hue alone.
# ---------------------------------------------------------------------------
RAIL_COLOURS = ["#d03b3b", "#e08a1e", "#0ca30c", "#2a78d6", "#8b5cf6", "#0f9b8e"]

BUS_COLOURS = {
    "usb":      "#2a78d6",
    "spi":      "#8b5cf6",
    "i2c":      "#0f9b8e",
    "uart":     "#e08a1e",
    "can":      "#c2410c",
    "ethernet": "#0ca30c",
    "i2s":      "#a16207",
    "swd":      "#64748b",
    "gpio":     "#6b7280",
    "analog":   "#d03b3b",
    "rf":       "#db2777",
}
BUS_DEFAULT = "#52514e"

POWER_KINDS = {"connector", "regulator", "power"}
KINDS = POWER_KINDS | {"mcu", "memory", "sensor", "radio", "analog",
                       "actuator", "interface", "logic", "other"}

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
BLOCK   = {"light": "#ffffff", "dark": "#242422"}
INK     = {"light": "#0b0b0b", "dark": "#ffffff"}
INK2    = {"light": "#52514e", "dark": "#c3c2b7"}
MUTED   = "#898781"
AXIS    = {"light": "#c3c2b7", "dark": "#383835"}

FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")

# Layout
BOX_W, BOX_H = 186, 70
ROW_PITCH = 104
SPINE_PITCH = 30
PAD, HEADER_H = 24, 78


# ---------------------------------------------------------------------------
# Load and validate
# ---------------------------------------------------------------------------
def load(path: str) -> dict:
    if not os.path.exists(path):
        raise SystemExit(f"{path}: no block diagram spec. "
                         f"Copy the template from the plugin's templates/project/hw/.")
    with open(path) as fh:
        spec = yaml.safe_load(fh) or {}
    if not spec.get("blocks"):
        raise SystemExit(f"{path}: no blocks defined")
    return spec


def bus_nodes(bus: dict) -> list[str]:
    """Every block a bus touches, controller first."""
    if bus.get("between"):
        return list(bus["between"])
    nodes = []
    if bus.get("controller"):
        nodes.append(bus["controller"])
    nodes.extend(bus.get("members") or [])
    return nodes


def validate(spec: dict) -> tuple[list[str], list[str]]:
    """Structural problems (errors) and things worth a human's eye (warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    blocks = spec["blocks"]
    rails = spec.get("rails") or []
    buses = spec.get("buses") or []

    bids = [b.get("id") for b in blocks]
    rids = [r.get("id") for r in rails]

    for dup in sorted({i for i in bids if bids.count(i) > 1}):
        errors.append(f"duplicate block id: {dup}")
    for dup in sorted({i for i in rids if rids.count(i) > 1}):
        errors.append(f"duplicate rail id: {dup}")

    for b in blocks:
        if not b.get("id"):
            errors.append(f"block with no id: {b.get('name', '?')}")
        kind = b.get("kind", "other")
        if kind not in KINDS:
            warnings.append(f"{b.get('id')}: unknown kind {kind!r}, drawn as 'other'")

    # ---- power tree ------------------------------------------------------
    for r in rails:
        rid = r.get("id")
        if not rid:
            errors.append(f"rail with no id: {r}")
            continue
        if r.get("voltage") is None:
            errors.append(f"rail {rid}: no voltage")
        if r.get("source") and r["source"] not in bids:
            errors.append(f"rail {rid}: source {r['source']!r} is not a block")
        parent = r.get("from")
        if parent and parent not in rids:
            errors.append(f"rail {rid}: fed from {parent!r}, which is not a rail")

    # Cycles in the tree make the budget meaningless, so they are errors.
    for r in rails:
        seen, cur = set(), r.get("id")
        while cur:
            if cur in seen:
                errors.append(f"power tree has a cycle through rail {cur}")
                break
            seen.add(cur)
            nxt = next((x.get("from") for x in rails if x.get("id") == cur), None)
            cur = nxt

    # A step-up that is not declared as one is usually a typo in the voltage.
    by_rail = {r.get("id"): r for r in rails}
    for r in rails:
        parent = by_rail.get(r.get("from"))
        if parent and r.get("voltage") is not None and parent.get("voltage") is not None:
            if r["voltage"] > parent["voltage"]:
                warnings.append(f"rail {r['id']} ({r['voltage']} V) is higher than its "
                                f"parent {parent['id']} ({parent['voltage']} V) — "
                                f"that needs a boost converter; is the voltage right?")

    # ---- loads -----------------------------------------------------------
    for b in blocks:
        for load_ in b.get("powered_by") or []:
            rail = load_.get("rail")
            if rail not in rids:
                errors.append(f"{b.get('id')}: powered by {rail!r}, which is not a rail")
            if load_.get("typ_current_a") is None and load_.get("max_current_a") is None:
                warnings.append(f"{b.get('id')} on {rail}: no current declared — "
                                f"it will not appear in the budget")
        if not (b.get("powered_by") or []) and b.get("kind") != "connector":
            warnings.append(f"{b.get('id')}: nothing powers it")

    # ---- buses -----------------------------------------------------------
    for bus in buses:
        if not bus.get("id"):
            errors.append(f"bus with no id: {bus}")
        nodes = bus_nodes(bus)
        if len(nodes) < 2:
            errors.append(f"bus {bus.get('id')}: needs at least two blocks")
        for n in nodes:
            if n not in bids:
                errors.append(f"bus {bus.get('id')}: {n!r} is not a block")

    on_a_bus = {n for bus in buses for n in bus_nodes(bus)}
    for b in blocks:
        if b.get("id") not in on_a_bus and b.get("kind") not in POWER_KINDS:
            warnings.append(f"{b.get('id')}: on no bus — is it really unconnected?")

    return errors, warnings


# ---------------------------------------------------------------------------
# Power budget
# ---------------------------------------------------------------------------
def budget(spec: dict) -> list[dict]:
    """Per rail: what it must deliver, against what its source can supply.

    A rail carries its own loads plus everything drawn by the rails derived
    from it, **referred through the voltage ratio**. A child rail's amps are
    not the parent's amps: 67 A at 48 V is 8.0 A off a 400 V input, and adding
    the 67 A straight on declares the 400 V rail eight times over budget when
    it is fine. Power is what crosses a converter, so the current referred up
    is `I_child × V_child / V_parent`.

    Efficiency is deliberately not modelled — this is a headroom check, not an
    energy model, and pretending to know a converter's curve at an unknown
    operating point would be worse than the honest conservative number. The
    referred current is therefore the ideal one, and it is optimistic by
    exactly the converter's loss. Where that matters (a battery-life claim, a
    thermal budget), work the number out explicitly and record it in an ADR.

    A rail with no declared voltage cannot be referred, so its children roll up
    1:1 and the rail is flagged; see validate().
    """
    rails = spec.get("rails") or []
    blocks = spec["blocks"]
    rows: dict[str, dict] = {}

    for r in rails:
        rid = r["id"]
        rows[rid] = {
            "id": rid, "voltage": r.get("voltage"), "from": r.get("from"),
            "source": r.get("source"), "limit": r.get("max_current_a"),
            "typ": 0.0, "max": 0.0, "loads": [], "notes": r.get("notes"),
            "unreferred": [],
        }

    for b in blocks:
        for load_ in b.get("powered_by") or []:
            row = rows.get(load_.get("rail"))
            if row is None:
                continue
            typ = float(load_.get("typ_current_a") or 0.0)
            mx = float(load_.get("max_current_a") or typ)
            row["typ"] += typ
            row["max"] += mx
            row["loads"].append((b.get("id"), b.get("name", ""), typ, mx))

    # Roll child rails up into their parents, deepest first.
    def depth(rid: str) -> int:
        d, cur, seen = 0, rows.get(rid, {}).get("from"), set()
        while cur and cur not in seen:
            seen.add(cur)
            d += 1
            cur = rows.get(cur, {}).get("from")
        return d

    for rid in sorted(rows, key=depth, reverse=True):
        parent = rows[rid]["from"]
        if parent not in rows:
            continue
        vc, vp = rows[rid]["voltage"], rows[parent]["voltage"]
        try:
            ratio = float(vc) / float(vp)
        except (TypeError, ValueError, ZeroDivisionError):
            # No usable voltage on one end. Roll up 1:1, which is conservative
            # for a step-down and wrong for a step-up, and say so rather than
            # inventing a ratio.
            ratio = 1.0
            rows[parent]["unreferred"].append(rid)
        typ, mx = rows[rid]["typ"] * ratio, rows[rid]["max"] * ratio
        rows[parent]["typ"] += typ
        rows[parent]["max"] += mx
        label = f"(rail {rid} and everything on it)"
        if ratio != 1.0:
            label += f" referred at {vc} V / {vp} V"
        rows[parent]["loads"].append((rid, label, typ, mx))

    for row in rows.values():
        limit = row["limit"]
        row["headroom"] = None if limit is None else limit - row["max"]
        row["over"] = limit is not None and row["max"] > limit
        row["tight"] = limit is not None and not row["over"] and row["max"] > 0.8 * limit

    return [rows[r["id"]] for r in rails]


# ---------------------------------------------------------------------------
# Layout — one model, two emitters, so the outputs cannot drift.
#
# The diagram is two panels, because power and data want different shapes and
# forcing them into one picture is what makes block diagrams unreadable. The
# power tree is an indented tree with a budget gauge on every rail; the
# functional diagram is blocks and buses, with each block's power domain shown
# as a badge rather than a line. Nothing has to cross anything.
# ---------------------------------------------------------------------------
RAIL_ROW_H, CHIP_H = 46, 18
INDENT = 22


def _rail_tree(rails: list[dict]) -> list[tuple[dict, int]]:
    """Rails depth-first from the externally-fed roots, with their depth."""
    kids: dict[str | None, list[dict]] = {}
    for r in rails:
        kids.setdefault(r.get("from"), []).append(r)
    ids = {r["id"] for r in rails}
    out: list[tuple[dict, int]] = []

    def walk(parent, depth):
        for r in kids.get(parent, []):
            out.append((r, depth))
            walk(r["id"], depth + 1)

    walk(None, 0)
    # A rail whose parent does not exist is an error elsewhere; still draw it.
    for r in rails:
        if r.get("from") not in ids and r.get("from") is not None:
            out.append((r, 0))
    return out


def _corridor_of(bus: dict, col: dict[str, int], nodes_ok: bool = False) -> int:
    """Which column corridor a multi-member bus will hang its spine in."""
    cols = [col[n] for n in bus_nodes(bus) if n in col]
    return min(cols) if cols else 0


def layout(spec: dict, keep: dict[str, tuple[float, float]] | None = None) -> dict:
    blocks = spec["blocks"]
    rails = spec.get("rails") or []
    buses = spec.get("buses") or []
    keep = keep or {}

    by_id = {b["id"]: b for b in blocks}
    rows = {r["id"]: r for r in budget(spec)}
    rail_colour = {r["id"]: RAIL_COLOURS[i % len(RAIL_COLOURS)]
                   for i, r in enumerate(rails)}

    # ---- panel A: power tree --------------------------------------------
    tree = _rail_tree(rails)
    rail_rows = []
    y = HEADER_H + 20
    for r, depth in tree:
        row = rows.get(r["id"], {})
        loads = [(bid, mx) for bid, _n, _t, mx in row.get("loads", [])
                 if bid in by_id]
        rail_rows.append({
            "id": r["id"], "depth": depth, "y": float(y),
            "x": float(PAD + depth * INDENT),
            "voltage": r.get("voltage"), "colour": rail_colour[r["id"]],
            "source": r.get("source"), "from": r.get("from"),
            "limit": r.get("limit", r.get("max_current_a")),
            "typ": row.get("typ", 0.0), "max": row.get("max", 0.0),
            "over": row.get("over", False), "tight": row.get("tight", False),
            "loads": sorted(loads, key=lambda l: -l[1]),
            "notes": r.get("notes"),
        })
        y += RAIL_ROW_H

    panel_b_y = y + 34 if rails else HEADER_H + 20

    # ---- panel B: functional blocks --------------------------------------
    # Column 0 is the power domain — what brings power in and what converts it.
    # Everything else ranks by hops from there across the bus graph, which puts
    # the MCU beside what feeds it and the peripherals out beyond it.
    adj: dict[str, set[str]] = {b["id"]: set() for b in blocks}
    for bus in buses:
        nodes_ = [n for n in bus_nodes(bus) if n in adj]
        for i, a in enumerate(nodes_):
            for b in nodes_[i + 1:]:
                adj[a].add(b)
                adj[b].add(a)

    col: dict[str, int] = {}
    frontier = [b["id"] for b in blocks if b.get("kind") in POWER_KINDS]
    for bid in frontier:
        col[bid] = 0
    depth = 0
    while frontier:
        depth += 1
        nxt = []
        for bid in frontier:
            for n in sorted(adj[bid]):
                if n not in col:
                    col[n] = depth
                    nxt.append(n)
        frontier = nxt
    for b in blocks:
        col.setdefault(b["id"], max(col.values(), default=-1) + 1)

    columns: dict[int, list[str]] = {}
    for b in blocks:
        columns.setdefault(col[b["id"]], []).append(b["id"])

    # Order within each column so connected blocks sit level with each other.
    #
    # Without this the rows are whatever order the spec happens to list, and
    # every link that is not horizontal has to cross something. Sweeping the
    # median of each node's neighbours back and forth is the standard fix and
    # costs nothing at this size: a handful of passes settles it, and blocks
    # that talk to each other end up side by side, which is also how a person
    # would draw it.
    order: dict[int, list[str]] = {c: list(ids) for c, ids in columns.items()}
    cols_sorted = sorted(order)

    def median_of(bid: str, other: int) -> float:
        peers = [order[other].index(n) for n in adj[bid] if col.get(n) == other]
        if not peers:
            return -1.0
        peers.sort()
        return peers[len(peers) // 2]

    for _sweep in range(4):
        for direction in (1, -1):
            seq = cols_sorted if direction == 1 else cols_sorted[::-1]
            for c in seq:
                ref = c - direction
                if ref not in order:
                    continue
                keyed = [(median_of(b, ref), i, b)
                         for i, b in enumerate(order[c])]
                # A node with no neighbour in the reference column keeps its
                # place rather than being flung to the top.
                fallback = {b: i for i, b in enumerate(order[c])}
                keyed.sort(key=lambda t: (t[0] if t[0] >= 0 else fallback[t[2]],
                                          t[1]))
                order[c] = [b for _m, _i, b in keyed]

    # Corridors carry the bus spines, which run vertically between columns
    # rather than horizontally underneath everything. A spine below the blocks
    # means every member drops a stub past every row under it, and those stubs
    # cross each other and the blocks; in the corridor a spine crosses nothing.
    # Every bus can need a lane in the corridor it starts from, and so can
    # every link between adjacent columns, so size for the worst column.
    per_col: dict[int, int] = {}
    for bus in buses:
        cs = [col[n] for n in bus_nodes(bus) if n in col]
        if cs:
            per_col[min(cs)] = per_col.get(min(cs), 0) + 1
    bus_lanes = max(per_col.values(), default=1)
    corr = min(max(76 + 20 * bus_lanes, 130), 280)
    pitch = BOX_W + corr

    nodes: dict[str, dict] = {}
    tallest = max((len(v) for v in order.values()), default=1)
    for c in cols_sorted:
        ids = order[c]
        # Centre each column on the tallest one, so the panel does not read as
        # a filled grid with ragged holes in it.
        top = panel_b_y + (tallest - len(ids)) * ROW_PITCH / 2
        for row_i, bid in enumerate(ids):
            x = PAD + c * pitch
            yy = top + row_i * ROW_PITCH
            if bid in keep:                   # a hand-tidied position wins
                x, yy = keep[bid]
            b = by_id[bid]
            nodes[bid] = {
                "id": bid, "x": float(x), "y": float(yy), "w": BOX_W, "h": BOX_H,
                "col": c, "name": b.get("name", bid), "part": b.get("part"),
                "kind": b.get("kind", "other"),
                "rails": [l.get("rail") for l in (b.get("powered_by") or [])],
            }

    blocks_b = max((n["y"] + n["h"] for n in nodes.values()), default=panel_b_y)

    # ---- buses -----------------------------------------------------------
    # Two problems have to be solved together, and solving only one of them
    # leaves the picture looking exactly as broken as before:
    #
    #   * Every connection used to leave a block at its vertical centre. A
    #     block with four of them — an MCU always has four — drew four lines
    #     out of one point, on top of each other.
    #   * Every vertical run used to sit at the same x. Two links between the
    #     same pair of columns therefore shared a corridor lane and overlapped
    #     for their whole length.
    #
    # So: fan the connections out along each block's edge, and give every
    # vertical run its own lane in its corridor.
    conns: dict[str, list[dict]] = {bid: [] for bid in nodes}
    plan: list[dict] = []
    for bus in buses:
        members = [n for n in bus_nodes(bus) if n in nodes]
        if len(members) < 2:
            continue
        colour = BUS_COLOURS.get(bus.get("kind", ""), BUS_DEFAULT)
        controller = bus.get("controller")
        if len(members) == 2:
            a_id, b_id = members
            if nodes[a_id]["x"] > nodes[b_id]["x"]:
                a_id, b_id = b_id, a_id
            item = {"type": "link", "id": bus["id"], "kind": bus.get("kind", "other"),
                    "colour": colour, "a": a_id, "b": b_id,
                    "notes": bus.get("notes"), "controller": controller}
            conns[a_id].append({"item": item, "side": "right",
                                "toward": nodes[b_id]["y"]})
            conns[b_id].append({"item": item, "side": "left",
                                "toward": nodes[a_id]["y"]})
        else:
            anchor = min(nodes[m]["col"] for m in members)
            item = {"type": "spine", "id": bus["id"], "kind": bus.get("kind", "other"),
                    "colour": colour, "notes": bus.get("notes"),
                    "controller": controller, "members": members,
                    "anchor": anchor}
            for m in members:
                side = "right" if nodes[m]["col"] <= anchor else "left"
                conns[m].append({"item": item, "side": side,
                                 "toward": nodes[m]["y"]})
        plan.append(item)

    # Fan out along each edge, ordered by where the other end sits, so lines
    # leaving one block do not have to cross each other to get there.
    port: dict[tuple[str, int], float] = {}
    for bid, cs in conns.items():
        n = nodes[bid]
        for side in ("left", "right"):
            side_cs = [c for c in cs if c["side"] == side]
            side_cs.sort(key=lambda c: c["toward"])
            for i, c in enumerate(side_cs):
                y = n["y"] + n["h"] * (i + 1) / (len(side_cs) + 1)
                port[(bid, id(c["item"]))] = y

    # One lane allocator per corridor, shared by spines and link verticals.
    lane_of: dict[int, int] = {}

    def next_lane(anchor: int) -> float:
        i = lane_of.get(anchor, 0)
        lane_of[anchor] = i + 1
        # 40 px clear of the block edge, 19 px between lanes: at 24/15 the
        # first spine sat almost on the block it came from and the next lane
        # was close enough to read as the same line.
        return PAD + anchor * pitch + BOX_W + 40 + i * 19

    links, spines = [], []
    for item in plan:
        if item["type"] == "spine":
            sx = next_lane(item["anchor"])
            stubs = []
            for m in item["members"]:
                y = port[(m, id(item))]
                side = "right" if nodes[m]["col"] <= item["anchor"] else "left"
                stubs.append({"id": m, "y": y,
                              "left_x": nodes[m]["x"],
                              "right_x": nodes[m]["x"] + nodes[m]["w"],
                              "side": side, "controller": m == item["controller"]})
            ys = [st["y"] for st in stubs]
            spines.append({**item, "stubs": stubs, "x": float(sx),
                           "top": float(min(ys)), "bottom": float(max(ys))})
        else:
            a, b = nodes[item["a"]], nodes[item["b"]]
            y1, y2 = port[(item["a"], id(item))], port[(item["b"], id(item))]
            # A straight run needs no corridor lane and cannot collide.
            mx = None if abs(y1 - y2) < 0.5 else next_lane(a["col"])
            links.append({**item, "y1": float(y1), "y2": float(y2),
                          "x1": float(a["x"] + a["w"]), "x2": float(b["x"]),
                          "mx": None if mx is None else float(mx)})

    # A legend strip under the blocks names every bus, so the diagram itself
    # carries only the lines and the reader still gets the kind and the notes.
    legend = [{"id": b["id"], "kind": b.get("kind", "other"),
               "colour": BUS_COLOURS.get(b.get("kind", ""), BUS_DEFAULT),
               "notes": b.get("notes")} for b in buses]
    legend_y = blocks_b + 34

    right = max([n["x"] + n["w"] for n in nodes.values()] +
                [sp["x"] for sp in spines] + [PAD + 520], default=PAD + 520)
    width = int(right + 210 + PAD)
    height = int(legend_y + 22 * len(legend) + 52)
    return {"spec": spec, "nodes": nodes, "rails": rail_rows, "spines": spines,
            "links": links, "legend": legend, "legend_y": legend_y,
            "panel_b_y": panel_b_y, "rail_colour": rail_colour,
            "width": max(width, 720), "height": height}


# ---------------------------------------------------------------------------
# SVG emitter — the review image. Theme-aware so one file reads in both.
# ---------------------------------------------------------------------------
def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _amps(a: float) -> str:
    return f"{a * 1000:.0f} mA" if a < 1 else f"{a:.2f} A"


def render_svg(model: dict, budget_rows: list[dict]) -> str:
    spec, nodes = model["spec"], model["nodes"]
    W, H = model["width"], model["height"]
    over = [r for r in budget_rows if r["over"]]

    o: list[str] = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
      f'viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" '
      f'aria-label="Electrical block diagram: {_esc(spec.get("project", "project"))}, '
      f'{len(nodes)} blocks, {len(model["rails"])} rails, '
      f'{len(model.get("legend", []))} buses">')

    a("<style>")
    a(f".s{{fill:{SURFACE['light']}}} .bx{{fill:{BLOCK['light']};stroke:{AXIS['light']}}} "
      f".ink{{fill:{INK['light']}}} .ink2{{fill:{INK2['light']}}} "
      f".ax{{stroke:{AXIS['light']}}} .gt{{fill:{AXIS['light']}}}")
    a("@media (prefers-color-scheme:dark){"
      f".s{{fill:{SURFACE['dark']}}} .bx{{fill:{BLOCK['dark']};stroke:{AXIS['dark']}}} "
      f".ink{{fill:{INK['dark']}}} .ink2{{fill:{INK2['dark']}}} "
      f".ax{{stroke:{AXIS['dark']}}} .gt{{fill:{AXIS['dark']}}}}}")
    a(f".mut{{fill:{MUTED}}}")
    a(".t{font-size:12px} .tb{font-size:12.5px;font-weight:600} "
      ".ts{font-size:10px} .tr{font-size:11.5px;font-weight:600} "
      ".h{font-size:15px;font-weight:600} .hh{font-size:11px;font-weight:600;"
      "letter-spacing:0.06em}")
    a("</style>")
    a(f'<rect width="{W}" height="{H}" class="s" rx="6"/>')

    # ---- header ----------------------------------------------------------
    title = spec.get("project", "Block diagram")
    if spec.get("revision"):
        title += f"  ·  rev {spec['revision']}"
    a(f'<text x="{PAD}" y="27" class="h ink">{_esc(title)}</text>')
    sub = (f"{len(nodes)} blocks · {len(model['rails'])} rails · "
           f"{len(model.get('legend', []))} buses")
    if over:
        sub += " · OVER BUDGET: " + ", ".join(r["id"] for r in over)
    a(f'<text x="{PAD}" y="46" class="t ink2">{_esc(sub)}</text>')
    a(f'<text x="{PAD}" y="61" class="ts mut">generated from block-diagram.yaml '
      f'— edit the spec, not this file</text>')

    # ---- panel A: power tree --------------------------------------------
    if model["rails"]:
        a(f'<text x="{PAD}" y="{HEADER_H + 6}" class="hh mut">POWER TREE</text>')
    for r in model["rails"]:
        x, y, c = r["x"], r["y"], r["colour"]
        # Elbow back to the parent rail's row, drawn in the indent gutter, so
        # the tree structure is visible without any line crossing another.
        if r["depth"]:
            parent = next((p for p in model["rails"] if p["id"] == r["from"]), None)
            if parent:
                gx = parent["x"] + 9
                a(f'<path d="M{gx},{parent["y"] + 12} V{y + 10} H{x - 3}" '
                  f'fill="none" class="ax" stroke-width="1.2" opacity="0.6"/>')

        a(f'<rect x="{x}" y="{y - 2}" width="6" height="{RAIL_ROW_H - 14}" '
          f'rx="3" fill="{c}"/>')
        head = f'{r["id"]}  {r["voltage"]} V'
        if r["source"]:
            head += f'  ← {r["source"]}'
        a(f'<text x="{x + 14}" y="{y + 10}" class="tr" fill="{c}">{_esc(head)}</text>')

        # Budget gauge. The number is always written out; the bar is a second
        # encoding of it, never the only one.
        gx, gw = PAD + 260, 150
        limit = r["limit"]
        if limit:
            frac = min(r["max"] / limit, 1.0)
            a(f'<rect x="{gx}" y="{y}" width="{gw}" height="9" rx="4.5" '
              f'class="gt" opacity="0.5"/>')
            a(f'<rect x="{gx}" y="{y}" width="{max(gw * frac, 3):.1f}" height="9" '
              f'rx="4.5" fill="{"#d03b3b" if r["over"] else ("#e08a1e" if r["tight"] else c)}"/>')
            txt = (f'{_amps(r["max"])} max of {_amps(limit)}  '
                   f'({100 * r["max"] / limit:.0f}%)')
            if r["over"]:
                txt += "  ✕ OVER"
            elif r["tight"]:
                txt += "  ! tight"
        else:
            txt = f'{_amps(r["max"])} max · no limit declared'
        a(f'<text x="{gx + gw + 12}" y="{y + 9}" class="ts ink2">{_esc(txt)}</text>')

        # Loads on this rail, biggest first.
        chips = "  ".join(f'{bid} {_amps(mx)}' for bid, mx in r["loads"][:6])
        if len(r["loads"]) > 6:
            chips += f'  +{len(r["loads"]) - 6} more'
        if chips:
            a(f'<text x="{x + 14}" y="{y + 26}" class="ts mut">{_esc(chips)}</text>')

    # ---- panel B: functional blocks --------------------------------------
    if nodes:
        a(f'<text x="{PAD}" y="{model["panel_b_y"] - 14}" class="hh mut">'
          f'FUNCTIONAL BLOCKS AND DATA BUSES</text>')
    for n in nodes.values():
        a(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" '
          f'rx="5" class="bx" stroke-width="1.2"/>')
        a(f'<text x="{n["x"] + 10}" y="{n["y"] + 20}" class="tb ink">'
          f'{_esc(n["id"])} · {_esc(n["name"][:24])}</text>')
        if n["part"]:
            a(f'<text x="{n["x"] + 10}" y="{n["y"] + 36}" class="t ink2">'
              f'{_esc(str(n["part"])[:26])}</text>')
        a(f'<text x="{n["x"] + 10}" y="{n["y"] + 54}" class="ts mut">'
          f'{_esc(n["kind"].upper())}</text>')
        # Power domain as a badge, not a line — the tree above is where the
        # power story is told, and lines here would cross everything.
        bx = n["x"] + n["w"] - 10
        for rid in reversed(n["rails"]):
            c = model["rail_colour"].get(rid, MUTED)
            bw = 9 + len(str(rid)) * 6.0
            bx -= bw
            a(f'<rect x="{bx:.1f}" y="{n["y"] + 44}" width="{bw:.1f}" height="15" '
              f'rx="7.5" fill="{c}"/>')
            a(f'<text x="{bx + bw / 2:.1f}" y="{n["y"] + 55}" class="ts" '
              f'fill="#ffffff" text-anchor="middle">{_esc(rid)}</text>')
            bx -= 4

    # ---- data buses ------------------------------------------------------
    # A two-block bus is one line between two blocks. Only a bus with three or
    # more members gets a spine, and that spine runs vertically in the corridor
    # between columns — never in a band underneath everything, which is what
    # forced every member to drop a stub past every row below it and made the
    # lines cross each other and the blocks.
    for lk in model.get("links", []):
        c = lk["colour"]
        x1, y1, x2, y2 = lk["x1"], lk["y1"], lk["x2"], lk["y2"]
        if lk["mx"] is None:
            d = f"M{x1},{y1} H{x2 - 4}"
            lx, ly, anchor = (x1 + x2) / 2, y1 - 7, "middle"
        else:
            mx = lk["mx"]
            d = f"M{x1},{y1} H{mx} V{y2} H{x2 - 4}"
            lx, ly, anchor = mx + 5, (y1 + y2) / 2 + 3, "start"
        a(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="1.8" '
          f'stroke-linejoin="round"/>')
        a(f'<circle cx="{x1}" cy="{y1}" r="2.6" fill="{c}"/>')
        if lk.get("controller") == lk["a"] or not lk.get("controller"):
            a(f'<path d="M-5,-4 L-5,4 L2,0 z" transform="translate({x2 - 2},{y2})" '
              f'fill="{c}"/>')
        else:
            a(f'<circle cx="{x2 - 3}" cy="{y2}" r="3" fill="{c}"/>')
        a(f'<text x="{lx:.0f}" y="{ly:.0f}" class="ts" fill="{c}" '
          f'text-anchor="{anchor}">{_esc(lk["id"])}</text>')

    for sp in model["spines"]:
        c, stubs = sp["colour"], sp["stubs"]
        if not stubs:
            continue
        sx = sp["x"]
        a(f'<line x1="{sx}" y1="{sp["top"]}" x2="{sx}" y2="{sp["bottom"]}" '
          f'stroke="{c}" stroke-width="2.4" stroke-linecap="round"/>')
        a(f'<text x="{sx + 5}" y="{sp["top"] - 9}" class="ts" fill="{c}">'
          f'{_esc(sp["id"])}</text>')
        for st in stubs:
            edge_x = st["right_x"] if st["side"] == "right" else st["left_x"]
            a(f'<line x1="{edge_x}" y1="{st["y"]}" x2="{sx}" y2="{st["y"]}" '
              f'stroke="{c}" stroke-width="1.6"/>')
            a(f'<circle cx="{edge_x}" cy="{st["y"]}" r="2.6" fill="{c}"/>')
            if st["controller"]:
                a(f'<rect x="{sx - 4}" y="{st["y"] - 4}" width="8" height="8" '
                  f'rx="1.5" fill="{c}"/>')
            else:
                a(f'<circle cx="{sx}" cy="{st["y"]}" r="3.2" fill="{c}"/>')

    # ---- bus legend ------------------------------------------------------
    ly = model["legend_y"]
    a(f'<text x="{PAD}" y="{ly - 8}" class="tb ink2">DATA BUSES</text>')
    for i, bl in enumerate(model.get("legend", [])):
        yy = ly + 12 + i * 22
        a(f'<line x1="{PAD}" y1="{yy}" x2="{PAD + 22}" y2="{yy}" '
          f'stroke="{bl["colour"]}" stroke-width="2.4" stroke-linecap="round"/>')
        txt = f'{bl["id"]} · {bl["kind"].upper()}'
        if bl["notes"]:
            txt += f' — {bl["notes"]}'
        a(f'<text x="{PAD + 30}" y="{yy + 4}" class="ts ink2">{_esc(txt)}</text>')

    a(f'<text x="{PAD}" y="{H - 16}" class="ts mut">'
      f'■ bus controller · ● bus member · pill on a block = the rail it runs from '
      f'· every colour is also labelled</text>')
    a("</svg>")
    return "\n".join(o)


# ---------------------------------------------------------------------------
# draw.io emitter — the editable file. Uncompressed mxGraph XML, which draw.io
# and the VS Code extension both open directly and git can diff. Connections
# are real mxCell edges, so dragging a block keeps them attached.
# ---------------------------------------------------------------------------
def _style(**kw) -> str:
    return ";".join(f"{k.replace('_', '')}={v}" for k, v in kw.items()) + ";"


def render_drawio(model: dict) -> str:
    spec, nodes = model["spec"], model["nodes"]
    cells: list[str] = []

    def vertex(cid, value, style, x, y, w, h):
        cells.append(
            f'        <mxCell id="{_esc(cid)}" value="{_esc(value)}" '
            f'style="{_esc(style)}" parent="1" vertex="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
            f'as="geometry"/>\n        </mxCell>')

    def edge(cid, value, style, src, dst):
        cells.append(
            f'        <mxCell id="{_esc(cid)}" value="{_esc(value)}" '
            f'style="{_esc(style)}" parent="1" edge="1" '
            f'source="{_esc(src)}" target="{_esc(dst)}">\n'
            f'          <mxGeometry relative="1" as="geometry"/>\n'
            f'        </mxCell>')

    def label(cid, value, x, y, w, size=11, colour=MUTED, bold=1):
        vertex(cid, value,
               _style(text=1, html=1, fillColor="none", strokeColor="none",
                      align="left", verticalAlign="middle", fontSize=size,
                      fontColor=colour, fontStyle=bold),
               x, y, w, 18)

    title = spec.get("project", "Block diagram")
    if spec.get("revision"):
        title += f'  ·  rev {spec["revision"]}'
    label("title", title, PAD, 14, 520, size=16, colour=INK["light"])
    label("subtitle", "generated from block-diagram.yaml — edit the spec, not this file",
          PAD, 38, 520, size=10, bold=0)

    # ---- panel A: power tree --------------------------------------------
    if model["rails"]:
        label("hdr-power", "POWER TREE", PAD, HEADER_H - 4, 240, size=11)
    for r in model["rails"]:
        rid = f'rail-{r["id"]}'
        head = f'{r["id"]}  {r["voltage"]} V'
        if r["source"]:
            head += f'  ← {r["source"]}'
        limit = r["limit"]
        if limit:
            head += (f'  |  {_amps(r["max"])} max of {_amps(limit)} '
                     f'({100 * r["max"] / limit:.0f}%)')
            if r["over"]:
                head += "  ✕ OVER"
            elif r["tight"]:
                head += "  ! tight"
        else:
            head += f'  |  {_amps(r["max"])} max, no limit declared'
        loads = "  ".join(f'{bid} {_amps(mx)}' for bid, mx in r["loads"][:6])
        value = (f'<b>{html.escape(head)}</b>'
                 + (f'<br/><font color="#898781" style="font-size:9px">'
                    f'{html.escape(loads)}</font>' if loads else ""))
        vertex(rid, value,
               _style(rounded=1, whiteSpace="wrap", html=1,
                      fillColor="#ffffff", strokeColor=r["colour"],
                      strokeWidth=2, align="left", spacingLeft=8,
                      verticalAlign="middle", fontSize=11, arcSize=8),
               r["x"], r["y"] - 4, 470 - r["depth"] * INDENT, RAIL_ROW_H - 12)
        if r["depth"] and any(p["id"] == r["from"] for p in model["rails"]):
            edge(f'{rid}-from', "",
                 _style(edgeStyle="orthogonalEdgeStyle", rounded=0, html=1,
                        strokeColor=r["colour"], strokeWidth=1.5,
                        endArrow="block", endSize=6,
                        exitX=0, exitY=1, entryX=0, entryY=0.5),
                 f'rail-{r["from"]}', rid)

    # ---- panel B: functional blocks --------------------------------------
    if nodes:
        label("hdr-blocks", "FUNCTIONAL BLOCKS AND DATA BUSES",
              PAD, model["panel_b_y"] - 22, 360, size=11)
    for n in nodes.values():
        pills = " ".join(f'[{r}]' for r in n["rails"])
        value = f'<b>{html.escape(n["id"])} · {html.escape(n["name"])}</b>'
        if n["part"]:
            value += f'<br/>{html.escape(str(n["part"]))}'
        value += (f'<br/><font color="#898781" style="font-size:9px">'
                  f'{n["kind"].upper()}'
                  + (f'  ·  {html.escape(pills)}' if pills else "") + '</font>')
        vertex(n["id"], value,
               _style(rounded=1, whiteSpace="wrap", html=1, fillColor="#ffffff",
                      strokeColor="#c3c2b7", fontSize=12,
                      verticalAlign="middle", arcSize=8),
               n["x"], n["y"], n["w"], n["h"])

    # ---- buses -----------------------------------------------------------
    # Two-block buses are a real edge between the two blocks, so dragging
    # either one in draw.io keeps the connection attached.
    for lk in model.get("links", []):
        na, nb = nodes[lk["a"]], nodes[lk["b"]]
        edge(f'link-{lk["id"]}', lk["id"],
             _style(edgeStyle="orthogonalEdgeStyle", rounded=1, html=1,
                    strokeColor=lk["colour"], strokeWidth=1.8,
                    endArrow="block", endSize=6, fontSize=9,
                    fontColor=lk["colour"], exitX=1,
                    exitY=round((lk["y1"] - na["y"]) / na["h"], 3), entryX=0,
                    entryY=round((lk["y2"] - nb["y"]) / nb["h"], 3)),
             lk["a"], lk["b"])

    for sp in model["spines"]:
        if not sp["stubs"]:
            continue
        spid = f'spine-{sp["id"]}'
        lbl = f'{sp["id"]} · {sp["kind"].upper()}'
        if sp["notes"]:
            lbl += f' · {sp["notes"]}'
        # A tall thin bar in the corridor: the spine as a draggable object.
        vertex(spid, lbl,
               _style(rounded=1, whiteSpace="wrap", html=1,
                      fillColor=sp["colour"], strokeColor="none",
                      fontColor="#ffffff", fontSize=9, arcSize=40,
                      verticalAlign="top", align="center",
                      horizontal=0, spacingTop=6),
               sp["x"] - 7, sp["top"] - 10,
               14, max(sp["bottom"] - sp["top"] + 20, 60))
        for st in sp["stubs"]:
            nm = nodes[st["id"]]
            edge(f'{spid}-{st["id"]}', "",
                 _style(edgeStyle="orthogonalEdgeStyle", rounded=0, html=1,
                        strokeColor=sp["colour"], strokeWidth=1.6,
                        endArrow="block" if st["controller"] else "oval",
                        endFill=1, endSize=6,
                        exitX=1 if st["side"] == "right" else 0,
                        exitY=round((st["y"] - nm["y"]) / nm["h"], 3),
                        entryX=0.5, entryY=0.5),
                 st["id"], spid)

    name = _esc(title)
    body = "\n".join(cells)
    return (
        f'<mxfile host="MakeHardware" type="device">\n'
        f'  <diagram name="{name}" id="block-diagram">\n'
        f'    <mxGraphModel dx="{model["width"]}" dy="{model["height"]}" grid="1" '
        f'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
        f'page="1" pageScale="1" pageWidth="{model["width"]}" '
        f'pageHeight="{model["height"]}" math="0" shadow="0">\n'
        f'      <root>\n'
        f'        <mxCell id="0"/>\n'
        f'        <mxCell id="1" parent="0"/>\n'
        f'{body}\n'
        f'      </root>\n'
        f'    </mxGraphModel>\n'
        f'  </diagram>\n'
        f'</mxfile>\n')


def read_positions(path: str) -> dict[str, tuple[float, float]]:
    """Block positions from an existing .drawio, so hand tidying survives.

    Only plain block cells are read back. Rails and bus spines are laid out
    from the spec every time, because their geometry follows the blocks.
    """
    if not os.path.exists(path):
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        sys.stderr.write(f"note: {path} is not valid XML ({exc}); "
                         f"laying out from scratch\n")
        return {}
    out: dict[str, tuple[float, float]] = {}
    for cell in root.iter("mxCell"):
        cid = cell.get("id") or ""
        if cell.get("vertex") != "1" or cid.startswith(
                ("rail-", "spine-", "bus-", "hdr-", "title", "subtitle")):
            continue
        geo = cell.find("mxGeometry")
        if geo is None or geo.get("x") is None or geo.get("y") is None:
            continue
        out[cid] = (float(geo.get("x")), float(geo.get("y")))
    return out


# ---------------------------------------------------------------------------
# PNG, for slides and reviews that will not render SVG
# ---------------------------------------------------------------------------
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
]


def rasterise(svg_path: str, png_path: str, w: int, h: int) -> bool:
    chrome = next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None) \
        or shutil.which("chromium") or shutil.which("google-chrome")
    if not chrome:
        sys.stderr.write("note: no chromium found; skipping --png\n")
        return False

    # Chromium lays a bare SVG out inside a page with a body margin, which
    # clips the right and bottom edges. Wrap it in a zero-margin document.
    svg = open(svg_path).read()
    shim = os.path.join(os.path.dirname(os.path.abspath(png_path)),
                        ".block-diagram-shot.html")
    with open(shim, "w") as fh:
        fh.write("<!doctype html><meta charset='utf-8'>"
                 "<style>html,body{margin:0;padding:0;background:#fcfcfb}"
                 "svg{display:block}</style>" + svg)
    # Chromium's screenshot viewport does not match --window-size exactly, so
    # asking for the SVG's own size silently loses the bottom of the canvas.
    # Shoot something taller than needed and cut it back to size.
    scale, slack = 2, 200
    try:
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", f"--force-device-scale-factor={scale}",
             "--default-background-color=fcfcfbff",
             f"--screenshot={os.path.abspath(png_path)}",
             f"--window-size={w + slack},{h + slack}",
             f"--crash-dumps-dir={os.path.dirname(os.path.abspath(png_path))}",
             f"file://{shim}"],
            capture_output=True, text=True, timeout=120)
        if not os.path.exists(png_path):
            sys.stderr.write(f"note: chromium did not write a PNG:\n"
                             f"{proc.stderr[-600:]}\n")
            return False
    finally:
        if os.path.exists(shim):
            os.remove(shim)

    try:
        from PIL import Image
    except ImportError:
        return True                       # oversized but correct; better than nothing
    with Image.open(png_path) as im:
        want = (min(w * scale, im.width), min(h * scale, im.height))
        if im.size != want:
            im.crop((0, 0, *want)).save(png_path)
    return True


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_budget(spec: dict, rows: list[dict]) -> None:
    print(f"{spec.get('project', 'Project')} — power budget\n")
    if not rows:
        print("  no rails declared")
        return
    print(f"  {'rail':<8} {'V':>6} {'typ A':>8} {'max A':>8} {'limit A':>9} "
          f"{'headroom':>9}")
    for r in rows:
        limit = "—" if r["limit"] is None else f'{r["limit"]:.3f}'
        head = "—" if r["headroom"] is None else f'{r["headroom"]:+.3f}'
        flag = "  OVER BUDGET" if r["over"] else ("  tight" if r["tight"] else "")
        print(f'  {r["id"]:<8} {r["voltage"]:>6} {r["typ"]:>8.3f} {r["max"]:>8.3f} '
              f'{limit:>9} {head:>9}{flag}')
    print()

    # Say when a child rail's current was referred, because the number a
    # reader expects to see is the child's amps and it deliberately is not.
    referred = [(r["id"], bid, name) for r in rows
                for bid, name, _t, _m in r["loads"] if "referred at" in name]
    if referred:
        print("  Child rails are referred through the voltage ratio "
              "(I_child x V_child / V_parent), ideal — no converter loss:")
        for rid, bid, name in referred:
            print(f"      {rid} <- {bid} {name.split('referred at')[1].strip()}")
        print()
    for r in rows:
        if r.get("unreferred"):
            print(f'  {r["id"]}: could not refer '
                  f'{", ".join(r["unreferred"])} — a voltage is missing, so '
                  f'those rolled up 1:1 and this budget is wrong by the '
                  f'converter ratio.\n')

    for r in rows:
        if r["over"] or r["tight"]:
            word = "exceeds" if r["over"] else "is within 20% of"
            print(f'  {r["id"]}: max draw {r["max"]:.3f} A {word} the '
                  f'{r["limit"]} A the source can deliver. Contributors:')
            for bid, name, typ, mx in sorted(r["loads"], key=lambda l: -l[3]):
                print(f'      {mx:>8.3f} A max   {bid:<6} {name}')
            print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", default="hw/block-diagram.yaml")
    ap.add_argument("--drawio", default="hw/block-diagram.drawio")
    ap.add_argument("--out", default="docs/design/block-diagram.svg",
                    help="review image (SVG)")
    ap.add_argument("--png", action="store_true",
                    help="also write a PNG next to the SVG")
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--summary", action="store_true",
                    help="power budget only, no files written")
    ap.add_argument("--relayout", action="store_true",
                    help="ignore hand-tidied positions in the existing .drawio")
    args = ap.parse_args()

    spec = load(args.spec)
    errors, warnings = validate(spec)
    for w in warnings:
        sys.stderr.write(f"  warning: {w}\n")
    if errors:
        sys.stderr.write("Block diagram is not valid:\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1

    rows = budget(spec)
    over = [r for r in rows if r["over"]]

    if args.summary:
        print_budget(spec, rows)
        return 1 if over else 0

    if args.check:
        print(f"{args.spec}: valid ({len(spec['blocks'])} blocks, "
              f"{len(spec.get('rails') or [])} rails, "
              f"{len(spec.get('buses') or [])} buses)")
        if over:
            sys.stderr.write("Rails over budget: "
                             + ", ".join(r["id"] for r in over) + "\n")
            print_budget(spec, rows)
            return 1
        return 0

    keep = {} if args.relayout else read_positions(args.drawio)
    model = layout(spec, keep)

    os.makedirs(os.path.dirname(args.drawio) or ".", exist_ok=True)
    with open(args.drawio, "w") as fh:
        fh.write(render_drawio(model))
    print(f"wrote {args.drawio}" + (f" (kept {len(keep)} hand-placed blocks)"
                                    if keep else ""))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(render_svg(model, rows))
    print(f"wrote {args.out}")

    if args.png:
        png = os.path.splitext(args.out)[0] + ".png"
        if rasterise(args.out, png, model["width"], model["height"]):
            print(f"wrote {png}")

    print()
    print_budget(spec, rows)
    if over:
        sys.stderr.write("Rails over budget: "
                         + ", ".join(r["id"] for r in over) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
