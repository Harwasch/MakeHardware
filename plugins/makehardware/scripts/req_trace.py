#!/usr/bin/env python3
"""Traceability and coverage gate for the MakeHardware requirements tree.

StrictDoc already guarantees *referential* integrity: it refuses to build a
tree with a duplicate UID or a Parent pointing at a UID that does not exist.
What it does not judge is whether the decomposition is any *good*. That is
what this does.

It reports, and fails on, the five ways a hardware requirement set rots:

  orphan       a requirement that refines nothing, so nobody asked for it
  childless    a non-leaf level with no decomposition beneath it
  unverified   a leaf with no EVIDENCE, i.e. a claim with nothing behind it
  unlinked     a requirement with no File relation, so no design realises it
  stale        STATUS says Verified but EVIDENCE is empty, or vice versa

It also draws the tree, because a requirement set is a graph and a list of
UIDs is not a way to review one. `--map` writes an editable draw.io file and
an SVG that renders inline on github.com, with every parent/child edge, the
status of each requirement and the gaps marked on the nodes that have them.
That is the artefact a human is asked to review at the requirements
milestone; see the `hw-review` skill.

Usage:
    scripts/req_trace.py                 # human-readable report
    scripts/req_trace.py --json          # machine-readable
    scripts/req_trace.py --gate          # exit 1 if any gap is found
    scripts/req_trace.py --map           # write the requirements map (drawio + svg)

The gate is what a design sprint runs before it claims a stage is complete.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

# UID prefix -> decomposition level. Lower refines higher.
LEVELS = {"VIS": 0, "SYS": 1, "ELE": 2, "MEC": 2, "FW": 2, "MFG": 2}
TOP = "VIS"          # the only level allowed to have no parent
LEAF_LEVEL = 2       # levels at or below this must carry evidence

STRICTDOC = os.environ.get("STRICTDOC_BIN") or shutil.which("strictdoc") \
            or "/opt/hw-py/bin/strictdoc"


def load(req_dir: str) -> list[dict]:
    """Export the tree to JSON via strictdoc and flatten the requirements."""
    out = tempfile.mkdtemp(prefix="reqtrace-")
    try:
        r = subprocess.run(
            [STRICTDOC, "export", req_dir, "--output-dir", out, "--formats=json"],
            capture_output=True, text=True,
        )
        index = os.path.join(out, "json", "index.json")
        if not os.path.exists(index):
            sys.stderr.write(
                "req_trace: strictdoc could not build the tree.\n"
                "This is a hard error: a duplicate UID or a dangling parent.\n\n"
                + (r.stdout or "") + (r.stderr or "")
            )
            sys.exit(2)
        data = json.load(open(index))
    finally:
        shutil.rmtree(out, ignore_errors=True)

    reqs = []
    for doc in data.get("DOCUMENTS", []):
        for node in doc.get("NODES", []):
            if node.get("_NODE_TYPE") != "REQUIREMENT":
                continue
            rels = node.get("RELATIONS") or []
            reqs.append({
                "uid": node.get("UID"),
                "title": node.get("TITLE", ""),
                "doc": doc.get("TITLE", ""),
                "status": node.get("STATUS", ""),
                "verification": node.get("VERIFICATION", ""),
                "evidence": (node.get("EVIDENCE") or "").strip(),
                "budget": (node.get("BUDGET") or "").strip(),
                "parents": [r["VALUE"] for r in rels if r.get("TYPE") == "Parent"],
                "files": [r.get("VALUE", "") for r in rels if r.get("TYPE") == "File"],
            })
    return reqs


def level_of(uid: str) -> int | None:
    return LEVELS.get((uid or "").split("-")[0])


def analyse(reqs: list[dict]) -> dict:
    by_uid = {r["uid"]: r for r in reqs}
    children: dict[str, list[str]] = {r["uid"]: [] for r in reqs}
    for r in reqs:
        for p in r["parents"]:
            children.setdefault(p, []).append(r["uid"])

    findings = {k: [] for k in
                ("orphan", "childless", "unverified", "unlinked", "stale", "unknown_level")}

    for r in reqs:
        uid = r["uid"]
        lvl = level_of(uid)
        if lvl is None:
            findings["unknown_level"].append(
                f"{uid}: prefix is not one of {sorted(LEVELS)}")
            continue

        if lvl > LEVELS[TOP] and not r["parents"]:
            findings["orphan"].append(f"{uid} ({r['title']}) refines nothing")

        is_leaf = not children.get(uid)
        if is_leaf and lvl < LEAF_LEVEL:
            findings["childless"].append(
                f"{uid} ({r['title']}) is a level-{lvl} requirement with no decomposition")

        if is_leaf and lvl >= LEAF_LEVEL and not r["evidence"]:
            findings["unverified"].append(
                f"{uid} ({r['title']}) has no EVIDENCE for its {r['verification']} verification")

        if is_leaf and lvl >= LEAF_LEVEL and not r["files"]:
            findings["unlinked"].append(
                f"{uid} ({r['title']}) has no File relation to a design artefact")

        if r["status"] == "Verified" and not r["evidence"]:
            findings["stale"].append(f"{uid} is marked Verified with no EVIDENCE")
        if r["evidence"] and r["status"] in ("Draft",):
            findings["stale"].append(
                f"{uid} has EVIDENCE but is still Draft — promote it or drop the evidence")

    total = len(reqs)
    verified = sum(1 for r in reqs if r["status"] == "Verified")
    with_ev = sum(1 for r in reqs if r["evidence"])
    return {
        "total": total,
        "verified": verified,
        "with_evidence": with_ev,
        "coverage_pct": round(100.0 * with_ev / total, 1) if total else 0.0,
        "by_level": {
            name: sum(1 for r in reqs if (r["uid"] or "").split("-")[0] == name)
            for name in LEVELS
        },
        "findings": findings,
        "children": children,
        "by_uid": by_uid,
    }


def report(a: dict) -> None:
    print("Requirements traceability\n")
    print(f"  {a['total']} requirements   "
          f"{a['verified']} verified   "
          f"{a['with_evidence']} with evidence ({a['coverage_pct']}%)")
    levels = ", ".join(f"{k}:{v}" for k, v in a["by_level"].items() if v)
    print(f"  by level: {levels}\n")

    labels = {
        "unknown_level": "Unrecognised UID prefix",
        "orphan":        "Orphans (refine nothing)",
        "childless":     "Not decomposed",
        "unverified":    "No evidence",
        "unlinked":      "No design artefact linked",
        "stale":         "Status/evidence mismatch",
    }
    gaps = 0
    for key, label in labels.items():
        items = a["findings"][key]
        if not items:
            continue
        gaps += len(items)
        print(f"  {label} ({len(items)}):")
        for line in items:
            print(f"    - {line}")
        print()
    if gaps == 0:
        print("  No gaps.\n")
    else:
        print(f"  {gaps} gap(s).\n")


# ---------------------------------------------------------------------------
# The requirements map
#
# A requirement set is a graph, and the thing a human has to judge about it —
# does every number trace to something someone asked for, and is anything
# hanging loose — is a shape question. Reading it as a list of UIDs is how a
# gap survives a review.
#
# One model, two emitters, as with the block diagram: an SVG that renders
# inline on github.com (which is the only surface the human has when the agent
# is working in a cloud VM) and a draw.io file for anyone who wants to drag
# the boxes around.
# ---------------------------------------------------------------------------
STATUS_STYLE = {
    "Draft":       {"colour": "#898781", "glyph": "·", "label": "Draft"},
    "Agreed":      {"colour": "#2a78d6", "glyph": "=", "label": "Agreed"},
    "Implemented": {"colour": "#e08a1e", "glyph": "▶", "label": "Implemented"},
    "Verified":    {"colour": "#0ca30c", "glyph": "✓", "label": "Verified"},
    "Waived":      {"colour": "#8b5cf6", "glyph": "~", "label": "Waived"},
}
STATUS_ORDER = ["Draft", "Agreed", "Implemented", "Verified", "Waived"]
UNKNOWN_STATUS = {"colour": "#898781", "glyph": "?", "label": "no status"}

GAP_COLOUR = "#d03b3b"
GAP_LABEL = {
    "orphan":        "refines nothing",
    "childless":     "not decomposed",
    "unverified":    "no evidence",
    "unlinked":      "no design artefact",
    "stale":         "status/evidence mismatch",
    "unknown_level": "unrecognised prefix",
}

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
CARD    = {"light": "#ffffff", "dark": "#242422"}
INK     = {"light": "#0b0b0b", "dark": "#ffffff"}
INK2    = {"light": "#52514e", "dark": "#c3c2b7"}
MUTED   = "#898781"
AXIS    = {"light": "#c3c2b7", "dark": "#383835"}
FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")

NODE_W, NODE_H = 264, 90
COL_GAP, ROW_GAP = 104, 18
MAP_PAD, MAP_HEADER = 24, 96
COLUMN_TITLES = {0: "VISION — what was asked for",
                 1: "SYSTEM — testable at the product",
                 2: "DISCIPLINE — ELE / MEC / FW / MFG"}


def _clip(text: str, n: int) -> str:
    """Truncate on a word boundary, so a label never ends mid-word."""
    text = str(text)
    if len(text) <= n:
        return text
    cut = text[:n - 1].rstrip()
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut + "…"


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def gaps_by_uid(a: dict) -> dict[str, list[str]]:
    """Which requirement each finding is about, so it can be drawn on the node."""
    out: dict[str, list[str]] = {}
    for kind, lines in a["findings"].items():
        for line in lines:
            uid = line.split()[0].rstrip(":") if line.split() else ""
            if uid:
                out.setdefault(uid, []).append(kind)
    return out


def map_model(reqs: list[dict], a: dict) -> dict:
    """Place every requirement: column by decomposition depth, row by subtree."""
    by_uid = {r["uid"]: r for r in reqs}
    order = [r["uid"] for r in reqs]
    rank = {u: i for i, u in enumerate(order)}

    children: dict[str, list[str]] = {u: [] for u in order}
    for r in reqs:
        for p in r["parents"]:
            if p in children:
                children[p].append(r["uid"])
    for kids in children.values():
        kids.sort(key=lambda u: rank.get(u, 0))

    parent_of = {r["uid"]: next((p for p in r["parents"] if p in by_uid), None)
                 for r in reqs}

    # Column: the UID prefix says the intended level, but a requirement is
    # always drawn to the right of its parent even when the prefixes disagree.
    # A left-pointing edge is the sort of thing this picture exists to show.
    col: dict[str, int] = {}

    def column(u: str, seen: tuple = ()) -> int:
        if u in col:
            return col[u]
        if u in seen:                       # only reachable on a malformed tree
            return 0
        lvl = level_of(u)
        c = 0 if lvl is None else lvl
        p = parent_of.get(u)
        if p:
            c = max(c, column(p, seen + (u,)) + 1)
        col[u] = c
        return c

    for u in order:
        column(u)

    # Row: leaves take consecutive slots, a parent centres on its children.
    slot = [0.0]
    row: dict[str, float] = {}

    def place(u: str, seen: tuple = ()) -> float:
        if u in row:
            return row[u]
        kids = [k for k in children.get(u, []) if k not in seen and k != u]
        if not kids:
            row[u] = slot[0]
            slot[0] += 1.0
        else:
            ys = [place(k, seen + (u,)) for k in kids]
            row[u] = sum(ys) / len(ys)
        return row[u]

    for u in order:
        if not parent_of.get(u):
            place(u)
    for u in order:                          # anything a cycle left unplaced
        place(u)

    gaps = gaps_by_uid(a)
    nodes: dict[str, dict] = {}
    for u in order:
        r = by_uid[u]
        st = STATUS_STYLE.get(r["status"], UNKNOWN_STATUS)
        lvl = level_of(u)
        kid_count = len(children.get(u, []))
        nodes[u] = {
            "uid": u,
            "title": r["title"],
            "status": r["status"] or "—",
            "colour": st["colour"], "glyph": st["glyph"],
            "verification": r["verification"],
            "budget": r["budget"],
            "has_evidence": bool(r["evidence"]),
            "has_file": bool(r["files"]),
            "children": kid_count,
            # Only a leaf at the discipline level owes evidence and an
            # artefact. Marking a VIS- or a decomposed SYS- requirement red
            # for having neither is noise, and noise is how a real red mark
            # stops being read.
            "judged": kid_count == 0 and lvl is not None and lvl >= LEAF_LEVEL,
            "gaps": gaps.get(u, []),
            "col": col[u], "rowpos": row[u],
            "x": float(MAP_PAD + col[u] * (NODE_W + COL_GAP)),
            "y": float(MAP_HEADER + row[u] * (NODE_H + ROW_GAP)),
        }

    edges = [(p, u) for u, p in parent_of.items() if p]
    cols = max(col.values(), default=0) + 1
    width = MAP_PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP
    # The rightmost column header runs past its box, so make room for it.
    width = max(width, int(MAP_PAD * 2 + (cols - 1) * (NODE_W + COL_GAP)
                           + 7 * len(COLUMN_TITLES.get(cols - 1, ""))))
    height = int(max((n["y"] + NODE_H for n in nodes.values()),
                     default=MAP_HEADER) + 78)
    return {"nodes": nodes, "edges": edges, "columns": cols,
            "width": max(width, 760), "height": height, "analysis": a}


def render_map_svg(model: dict) -> str:
    nodes, W, H = model["nodes"], model["width"], model["height"]
    a = model["analysis"]
    gap_total = sum(len(v) for v in a["findings"].values())

    o: list[str] = []
    add = o.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" '
        f'aria-label="Requirements map: {a["total"]} requirements, '
        f'{a["verified"]} verified, {gap_total} gaps">')

    add("<style>")
    add(f".s{{fill:{SURFACE['light']}}} .card{{fill:{CARD['light']}}} "
        f".ink{{fill:{INK['light']}}} .ink2{{fill:{INK2['light']}}} "
        f".ax{{stroke:{AXIS['light']}}}")
    add("@media (prefers-color-scheme:dark){"
        f".s{{fill:{SURFACE['dark']}}} .card{{fill:{CARD['dark']}}} "
        f".ink{{fill:{INK['dark']}}} .ink2{{fill:{INK2['dark']}}} "
        f".ax{{stroke:{AXIS['dark']}}}}}")
    add(f".mut{{fill:{MUTED}}} .t{{font-size:11.5px}} "
        ".tb{font-size:12px;font-weight:600} .ts{font-size:10px} "
        ".h{font-size:16px;font-weight:600} .hd{font-size:11px;font-weight:600}")
    add("</style>")
    add(f'<rect width="{W}" height="{H}" class="s" rx="6"/>')

    add(f'<text x="{MAP_PAD}" y="30" class="h ink">Requirements map</text>')
    sub = (f'{a["total"]} requirements · {a["verified"]} verified · '
           f'{a["with_evidence"]} with evidence ({a["coverage_pct"]}%) · '
           + (f'{gap_total} gap(s), marked in red' if gap_total else "no gaps"))
    add(f'<text x="{MAP_PAD}" y="50" class="t ink2">{_esc(sub)}</text>')
    add(f'<text x="{MAP_PAD}" y="68" class="ts mut">'
        f'an arrow points from a requirement to the one that refines it</text>')

    for c in range(model["columns"]):
        cx = MAP_PAD + c * (NODE_W + COL_GAP)
        add(f'<text x="{cx}" y="{MAP_HEADER - 10}" class="hd ink2">'
            f'{_esc(COLUMN_TITLES.get(c, f"LEVEL {c}"))}</text>')

    add('<defs><marker id="ra" markerWidth="7" markerHeight="7" refX="6" refY="3" '
        f'orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="{MUTED}"/></marker></defs>')
    for parent, child in model["edges"]:
        if parent not in nodes or child not in nodes:
            continue
        p, k = nodes[parent], nodes[child]
        x1, y1 = p["x"] + NODE_W, p["y"] + NODE_H / 2
        x2, y2 = k["x"], k["y"] + NODE_H / 2
        mx = x1 + max(18, (x2 - x1) / 2)
        add(f'<path d="M{x1},{y1} H{mx} V{y2} H{x2 - 3}" fill="none" '
            f'stroke="{MUTED}" stroke-width="1.2" opacity="0.6" '
            f'marker-end="url(#ra)"/>')

    for n in nodes.values():
        x, y = n["x"], n["y"]
        # A gap gets an explicit red border; everything else takes the themed
        # axis colour from the stylesheet so the card reads in both themes.
        if n["gaps"]:
            add(f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" '
                f'class="card" stroke="{GAP_COLOUR}" stroke-width="2"/>')
        else:
            add(f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" '
                f'class="card ax" stroke-width="1"/>')
        add(f'<rect x="{x}" y="{y}" width="5" height="{NODE_H}" '
            f'fill="{n["colour"]}" rx="2.5"/>')
        add(f'<text x="{x + 14}" y="{y + 20}" class="tb ink">{_esc(n["uid"])}</text>')
        add(f'<text x="{x + NODE_W - 10}" y="{y + 20}" class="ts" '
            f'text-anchor="end" fill="{n["colour"]}">'
            f'{n["glyph"]} {_esc(n["status"])}</text>')
        add(f'<text x="{x + 14}" y="{y + 39}" class="t ink2">'
            f'{_esc(_clip(n["title"], 38))}</text>')

        # Two short lines rather than one long one: what closes this
        # requirement, then whether the things that close it exist yet.
        head = [b for b in (n["verification"],
                            f'budget {n["budget"]}' if n["budget"] else "") if b]
        add(f'<text x="{x + 14}" y="{y + 56}" class="ts mut">'
            f'{_esc(_clip(" · ".join(head), 42))}</text>')
        if n["judged"]:
            tx = x + 14
            for text, ok in (("evidence", n["has_evidence"]),
                             ("artefact linked", n["has_file"])):
                add(f'<text x="{tx}" y="{y + 70}" class="ts" '
                    f'fill="{MUTED if ok else GAP_COLOUR}">'
                    f'{"✓" if ok else "✕"} {_esc(text)}</text>')
                tx += 18 + len(text) * 5.3
        elif n["children"]:
            add(f'<text x="{x + 14}" y="{y + 70}" class="ts mut">'
                f'refined by {n["children"]} requirement'
                f'{"s" if n["children"] != 1 else ""}</text>')

        # The two evidence gaps are already drawn as the ✕ marks above; only
        # say the ones the badges cannot.
        rest = [g for g in n["gaps"] if not (n["judged"] and g in
                                             ("unverified", "unlinked"))]
        if rest:
            names = ", ".join(GAP_LABEL.get(g, g) for g in rest)
            add(f'<text x="{x + 14}" y="{y + 84}" class="ts" fill="{GAP_COLOUR}">'
                f'{_esc(_clip(names, 44))}</text>')

    ly = H - 30
    lx = MAP_PAD
    for st in STATUS_ORDER:
        meta = STATUS_STYLE[st]
        add(f'<rect x="{lx}" y="{ly - 9}" width="10" height="10" rx="2" '
            f'fill="{meta["colour"]}"/>')
        add(f'<text x="{lx + 15}" y="{ly}" class="ts ink2">'
            f'{meta["glyph"]} {_esc(st)}</text>')
        lx += 15 + len(st) * 6.4 + 30
    add(f'<rect x="{lx}" y="{ly - 9}" width="10" height="10" rx="2" fill="none" '
        f'stroke="{GAP_COLOUR}" stroke-width="2"/>')
    add(f'<text x="{lx + 15}" y="{ly}" class="ts ink2">red border = a gap the '
        f'gate is failing on</text>')
    add("</svg>")
    return "\n".join(o)


def _dstyle(**kw) -> str:
    return ";".join(f"{k.replace('_', '')}={v}" for k, v in kw.items()) + ";"


def render_map_drawio(model: dict) -> str:
    nodes = model["nodes"]
    a = model["analysis"]
    cells: list[str] = []

    def vertex(cid, value, style, x, y, w, h):
        cells.append(
            f'        <mxCell id="{_esc(cid)}" value="{_esc(value)}" '
            f'style="{_esc(style)}" parent="1" vertex="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
            f'as="geometry"/>\n        </mxCell>')

    def edge(cid, style, src, dst):
        cells.append(
            f'        <mxCell id="{_esc(cid)}" style="{_esc(style)}" parent="1" '
            f'edge="1" source="{_esc(src)}" target="{_esc(dst)}">\n'
            f'          <mxGeometry relative="1" as="geometry"/>\n'
            f'        </mxCell>')

    def label(cid, value, x, y, w, size=11, colour=MUTED, bold=1):
        vertex(cid, value,
               _dstyle(text=1, html=1, fillColor="none", strokeColor="none",
                       align="left", verticalAlign="middle", fontSize=size,
                       fontColor=colour, fontStyle=bold), x, y, w, 18)

    gap_total = sum(len(v) for v in a["findings"].values())
    label("title", "Requirements map", MAP_PAD, 16, 420, size=16,
          colour=INK["light"])
    label("subtitle",
          f'{a["total"]} requirements · {a["verified"]} verified · '
          f'{a["coverage_pct"]}% with evidence · {gap_total} gap(s) · '
          f'generated by req-trace --map',
          MAP_PAD, 40, 620, size=10, bold=0)
    for c in range(model["columns"]):
        label(f"col-{c}", COLUMN_TITLES.get(c, f"LEVEL {c}"),
              MAP_PAD + c * (NODE_W + COL_GAP), MAP_HEADER - 18, NODE_W, size=11)

    for n in nodes.values():
        badges = []
        if n["verification"]:
            badges.append(n["verification"])
        if n["budget"]:
            badges.append(f'budget {n["budget"]}')
        if n["judged"]:
            badges.append("evidence" if n["has_evidence"] else "NO EVIDENCE")
            badges.append("artefact" if n["has_file"] else "NO ARTEFACT")
        elif n["children"]:
            badges.append(f'refined by {n["children"]}')
        value = (f'<b>{html.escape(n["uid"])}</b>  '
                 f'<font color="{n["colour"]}">{n["glyph"]} '
                 f'{html.escape(n["status"])}</font>'
                 f'<br/>{html.escape(_clip(n["title"], 44))}'
                 f'<br/><font color="{MUTED}" style="font-size:9px">'
                 f'{html.escape(" · ".join(badges))}</font>')
        if n["gaps"]:
            names = ", ".join(GAP_LABEL.get(g, g) for g in n["gaps"])
            value += (f'<br/><font color="{GAP_COLOUR}" style="font-size:9px">'
                      f'{html.escape(names)}</font>')
        vertex(n["uid"], value,
               _dstyle(rounded=1, whiteSpace="wrap", html=1, fillColor="#ffffff",
                       strokeColor=GAP_COLOUR if n["gaps"] else "#c3c2b7",
                       strokeWidth=2 if n["gaps"] else 1,
                       align="left", spacingLeft=8, verticalAlign="middle",
                       fontSize=11, arcSize=8),
               n["x"], n["y"], NODE_W, NODE_H)

    for parent, child in model["edges"]:
        if parent in nodes and child in nodes:
            edge(f"{parent}--{child}",
                 _dstyle(edgeStyle="orthogonalEdgeStyle", rounded=1, html=1,
                         strokeColor=MUTED, strokeWidth=1.2, endArrow="block",
                         endSize=6, exitX=1, exitY=0.5, entryX=0, entryY=0.5),
                 parent, child)

    body = "\n".join(cells)
    return (
        f'<mxfile host="MakeHardware" type="device">\n'
        f'  <diagram name="Requirements map" id="requirements-map">\n'
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


def write_map(reqs: list[dict], a: dict, svg_path: str, drawio_path: str) -> None:
    model = map_model(reqs, a)
    for path, text in ((svg_path, render_map_svg(model)),
                       (drawio_path, render_map_drawio(model))):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        print(f"wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("req_dir", nargs="?", default="requirements")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--gate", action="store_true", help="exit 1 when gaps are found")
    ap.add_argument("--map", action="store_true",
                    help="also write the requirements map (SVG + draw.io)")
    ap.add_argument("--map-svg", default="docs/design/requirements-map.svg")
    ap.add_argument("--map-drawio", default="docs/design/requirements-map.drawio")
    args = ap.parse_args()

    reqs = load(args.req_dir)
    a = analyse(reqs)
    gaps = sum(len(v) for v in a["findings"].values())

    if args.json:
        print(json.dumps({k: a[k] for k in
                          ("total", "verified", "with_evidence", "coverage_pct",
                           "by_level", "findings")}, indent=2))
    else:
        report(a)

    if args.map:
        write_map(reqs, a, args.map_svg, args.map_drawio)

    return 1 if (args.gate and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
