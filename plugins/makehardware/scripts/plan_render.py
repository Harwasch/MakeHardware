#!/usr/bin/env python3
"""Validate a project plan and render it as a dependency Gantt chart.

The plan is the agreement about what work exists, in what order, and what is
done. Each chunk is sized to roughly one AI session, so the horizontal axis is
sessions, not calendar time — which is the honest unit here, because nobody
knows how many wall-clock days a session will take.

    plan_render.py                      # validate, render SVG + draw.io, update README
    plan_render.py --check              # validate only; exit 1 if the plan is broken
    plan_render.py --summary            # text status, no files written

Chunks are scheduled by longest-path: a chunk starts as soon as every chunk it
depends on has finished. That makes the critical path fall out of the data
rather than being asserted, and it is drawn heavier than the rest.

`done` is checked against the world, not taken on trust. A chunk claiming to
be finished must have produced the files it declared in `outputs`, and, if it
declared a `review`, that review must be signed off in `docs/review/reviews.yaml`.
Optimistic statuses are the failure mode this renderer used to have: it drew
whatever it was told, and a plan nobody can disbelieve is worse than no plan.
"""
from __future__ import annotations

import argparse
import glob
import html
import os
import sys

import yaml

# review_gate lives beside this file and owns the sign-off ledger. Import it if
# it is there; a project that has not adopted reviews yet still renders.
try:
    import review_gate
except ImportError:                                   # pragma: no cover
    review_gate = None

# ---------------------------------------------------------------------------
# Palette. Status roles are reserved colours and are always paired with a glyph
# and a text label, so state never rides on hue alone.
# ---------------------------------------------------------------------------
STATUS = {
    "done":        {"light": "#0ca30c", "dark": "#0ca30c", "glyph": "✓", "label": "Done"},
    "in_progress": {"light": "#2a78d6", "dark": "#3987e5", "glyph": "▶", "label": "In progress"},
    "blocked":     {"light": "#d03b3b", "dark": "#d03b3b", "glyph": "✕", "label": "Blocked"},
    "todo":        {"light": "#898781", "dark": "#898781", "glyph": "○", "label": "To do"},
}
STATUS_ORDER = ["done", "in_progress", "blocked", "todo"]

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
INK     = {"light": "#0b0b0b", "dark": "#ffffff"}
INK2    = {"light": "#52514e", "dark": "#c3c2b7"}
MUTED   = "#898781"
AXIS    = {"light": "#c3c2b7", "dark": "#383835"}

FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")

# Layout
GUTTER, COL_W, ROW_H, BAR_H = 300, 116, 34, 20
BAND_H, PAD, HEADER_H = 28, 20, 82


# ---------------------------------------------------------------------------
# Load and validate
# ---------------------------------------------------------------------------
def load(path: str) -> dict:
    with open(path) as fh:
        plan = yaml.safe_load(fh) or {}
    if not plan.get("chunks"):
        raise SystemExit(f"{path}: no chunks defined")
    return plan


def validate(plan: dict) -> list[str]:
    """Structural problems that make a plan meaningless. Reported, not raised."""
    errors: list[str] = []
    chunks = plan["chunks"]
    ids = [c.get("id") for c in chunks]

    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"duplicate chunk id: {dup}")
    for c in chunks:
        if not c.get("id"):
            errors.append(f"chunk with no id: {c.get('title', '?')}")
        if c.get("status") not in STATUS:
            errors.append(f"{c.get('id')}: status {c.get('status')!r} "
                          f"is not one of {STATUS_ORDER}")
        for dep in c.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"{c['id']}: depends on {dep!r}, which does not exist")

    # Cycles make scheduling impossible, so find them explicitly.
    graph = {c["id"]: [d for d in (c.get("depends_on") or []) if d in ids]
             for c in chunks if c.get("id")}
    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle = " -> ".join(trail[trail.index(node):] + [node])
            errors.append(f"dependency cycle: {cycle}")
            return
        state[node] = 1
        for nxt in graph.get(node, []):
            visit(nxt, trail + [node])
        state[node] = 2

    for node in graph:
        visit(node, [])

    # A done chunk resting on unfinished work is a bookkeeping error, and it is
    # the one that quietly makes a status report wrong.
    by_id = {c["id"]: c for c in chunks if c.get("id")}
    for c in chunks:
        if c.get("status") == "done":
            for dep in c.get("depends_on") or []:
                if by_id.get(dep, {}).get("status") not in ("done", None):
                    errors.append(f"{c['id']} is done but depends on {dep}, "
                                  f"which is {by_id[dep].get('status')}")

    errors.extend(check_done_against_reality(plan))
    return errors


def missing_outputs(chunk: dict) -> list[str]:
    """Declared outputs that are not on disk.

    `outputs` entries are paths relative to the project root. A trailing
    slash, or any directory, is satisfied by the directory existing and
    containing something — an empty `sim/thermal/` is not a thermal analysis.
    """
    gone = []
    for out in chunk.get("outputs") or []:
        out = str(out)
        if any(ch in out for ch in "*?["):
            if not glob.glob(out):
                gone.append(out)
            continue
        if out.endswith("/") or os.path.isdir(out):
            if not os.path.isdir(out.rstrip("/")) or not os.listdir(out.rstrip("/")):
                gone.append(out)
        elif not os.path.exists(out):
            gone.append(out)
    return gone


def review_state(chunk: dict, ledger: str = "docs/review/reviews.yaml") -> tuple[str, str] | None:
    """(state, detail) for the chunk's declared review, or None if it declares none."""
    rid = chunk.get("review")
    if not rid or review_gate is None:
        return None
    data = review_gate.load(ledger)
    review = review_gate.find(data, rid)
    if review is None:
        return ("missing", f"no review {rid!r} has been requested")
    st = review_gate.state(review)
    if st == "approved":
        return ("approved", "")
    if st == "stale":
        return ("stale", ", ".join(review_gate.drifted(review)))
    if st == "changes_requested":
        return ("changes_requested", (review.get("note") or "").splitlines()[0][:60])
    return ("requested", "sent to the human, not yet answered")


def check_done_against_reality(plan: dict) -> list[str]:
    """`done` is a claim about the filesystem and about a human's agreement.

    Statuses drift optimistic — chunks get marked done while the layout is
    unrouted and no fab output exists — and a renderer that draws whatever it
    is told cannot catch that. So check: did the declared outputs appear, and
    did the human sign off where the chunk said they would.
    """
    errors: list[str] = []
    ledger = plan.get("review_ledger", "docs/review/reviews.yaml")
    for c in plan["chunks"]:
        if c.get("status") != "done":
            continue
        cid = c.get("id", "?")
        for out in missing_outputs(c):
            errors.append(f"{cid} is done but its output {out!r} does not exist")
        rv = review_state(c, ledger)
        if rv is None:
            continue
        st, detail = rv
        if st == "approved":
            continue
        wording = {
            "missing":           f"declares review {c['review']!r}, which has never been requested",
            "requested":         f"is waiting on review {c['review']!r} — {detail}",
            "changes_requested": f"review {c['review']!r} asked for changes: {detail}",
            "stale":             f"review {c['review']!r} was approved, then {detail} changed",
        }[st]
        errors.append(f"{cid} is done but {wording}")
    return errors


def schedule(plan: dict) -> tuple[dict, int]:
    """Earliest-start scheduling. Returns {id: (start, span)} and total width."""
    chunks = plan["chunks"]
    by_id = {c["id"]: c for c in chunks}
    placed: dict[str, tuple[int, int]] = {}

    def place(cid: str, seen: frozenset = frozenset()) -> tuple[int, int]:
        if cid in placed:
            return placed[cid]
        if cid in seen:                       # cycle; validate() already flagged it
            return (0, 1)
        c = by_id[cid]
        deps = [d for d in (c.get("depends_on") or []) if d in by_id]
        start = max((place(d, seen | {cid})[0] + place(d, seen | {cid})[1]
                     for d in deps), default=0)
        span = max(1, int(c.get("estimate_sessions", 1)))
        placed[cid] = (start, span)
        return placed[cid]

    for c in chunks:
        place(c["id"])
    total = max((s + w for s, w in placed.values()), default=1)
    return placed, total


def critical_path(plan: dict, placed: dict) -> set[str]:
    """The chain that sets the total length. Drawn heavier than the rest."""
    by_id = {c["id"]: c for c in plan["chunks"]}
    total = max((s + w for s, w in placed.values()), default=0)
    tail = [cid for cid, (s, w) in placed.items() if s + w == total]
    path: set[str] = set()
    stack = list(tail)
    while stack:
        cid = stack.pop()
        if cid in path:
            continue
        path.add(cid)
        start = placed[cid][0]
        for dep in by_id[cid].get("depends_on") or []:
            if dep in placed and placed[dep][0] + placed[dep][1] == start:
                stack.append(dep)
    return path


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def render_svg(plan: dict, placed: dict, total: int, crit: set[str]) -> str:
    chunks = plan["chunks"]

    # Group by discipline, keeping first-appearance order.
    order: list[str] = []
    groups: dict[str, list] = {}
    for c in chunks:
        d = c.get("discipline", "general")
        if d not in order:
            order.append(d)
            groups[d] = []
        groups[d].append(c)

    rows = len(chunks) + len(order)
    width = GUTTER + total * COL_W + PAD * 2
    height = HEADER_H + rows * ROW_H + 58 + PAD

    done = sum(1 for c in chunks if c.get("status") == "done")
    blocked = sum(1 for c in chunks if c.get("status") == "blocked")
    pct = round(100 * done / len(chunks)) if chunks else 0

    o: list[str] = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
      f'viewBox="0 0 {width} {height}" font-family="{FONT}" role="img" '
      f'aria-label="Project plan: {_esc(plan.get("project", "project"))}, '
      f'{done} of {len(chunks)} chunks done">')

    # Theme: light by default, dark under prefers-color-scheme so the chart is
    # readable in a dark README without a second file.
    a("<style>")
    a(f".s{{fill:{SURFACE['light']}}} .ink{{fill:{INK['light']}}} "
      f".ink2{{fill:{INK2['light']}}} .ax{{stroke:{AXIS['light']}}} "
      f".bar-in_progress{{fill:{STATUS['in_progress']['light']}}}")
    a("@media (prefers-color-scheme:dark){"
      f".s{{fill:{SURFACE['dark']}}} .ink{{fill:{INK['dark']}}} "
      f".ink2{{fill:{INK2['dark']}}} .ax{{stroke:{AXIS['dark']}}} "
      f".bar-in_progress{{fill:{STATUS['in_progress']['dark']}}}}}")
    a(f".mut{{fill:{MUTED}}} .bar-done{{fill:{STATUS['done']['light']}}} "
      f".bar-blocked{{fill:{STATUS['blocked']['light']}}} "
      f".bar-todo{{fill:{MUTED}}}")
    a(".crit{stroke:#0b0b0b;stroke-opacity:0.62;stroke-width:2}")
    a("@media (prefers-color-scheme:dark){"
      ".crit{stroke:#ffffff;stroke-opacity:0.72}}")
    a(".t{font-size:12px} .tb{font-size:12px;font-weight:600} "
      ".ts{font-size:10.5px} .h{font-size:15px;font-weight:600}")
    a("</style>")
    a(f'<rect width="{width}" height="{height}" class="s" rx="6"/>')

    # ---- header ----------------------------------------------------------
    a(f'<text x="{PAD}" y="27" class="h ink">{_esc(plan.get("project", "Project plan"))}</text>')
    sub = f"{done}/{len(chunks)} chunks complete · {pct}% · {total} sessions on the critical path"
    if blocked:
        sub += f" · {blocked} blocked"
    a(f'<text x="{PAD}" y="47" class="t ink2">{_esc(sub)}</text>')

    x0, y0 = PAD + GUTTER, HEADER_H

    # ---- session axis ----------------------------------------------------
    for i in range(total):
        cx = x0 + i * COL_W
        a(f'<line x1="{cx}" y1="{y0 - 6}" x2="{cx}" y2="{y0 + rows * ROW_H}" '
          f'class="ax" stroke-width="1" opacity="0.5"/>')
        a(f'<text x="{cx + 6}" y="{y0 - 10}" class="ts mut">S{i + 1}</text>')
    a(f'<line x1="{x0 + total * COL_W}" y1="{y0 - 6}" x2="{x0 + total * COL_W}" '
      f'y2="{y0 + rows * ROW_H}" class="ax" stroke-width="1" opacity="0.5"/>')

    # ---- rows ------------------------------------------------------------
    centre: dict[str, tuple[float, float, float]] = {}   # id -> (x_start, x_end, y)
    y = y0
    for disc in order:
        a(f'<text x="{PAD}" y="{y + 19}" class="tb ink2">{_esc(disc.upper())}</text>')
        a(f'<line x1="{PAD}" y1="{y + 25}" x2="{width - PAD}" y2="{y + 25}" '
          f'class="ax" stroke-width="1" opacity="0.35"/>')
        y += BAND_H
        for c in groups[disc]:
            cid = c["id"]
            st = c.get("status", "todo")
            meta = STATUS.get(st, STATUS["todo"])
            start, span = placed[cid]
            bx = x0 + start * COL_W + 3
            bw = span * COL_W - 6
            by = y + (ROW_H - BAR_H) / 2

            label = f'{cid} · {c.get("title", "")}'
            a(f'<text x="{PAD}" y="{y + ROW_H / 2 + 4}" class="t ink">'
              f'{_esc(label[:44])}</text>')

            # 4px rounded ends, 2px surface gap between adjacent bars.
            cls = f"bar-{st} crit" if cid in crit else f"bar-{st}"
            a(f'<rect x="{bx}" y="{by}" width="{bw}" height="{BAR_H}" rx="4" '
              f'class="{cls}"/>')
            # Glyph + label inside the bar: status never rides on colour alone.
            a(f'<text x="{bx + 8}" y="{by + BAR_H / 2 + 4}" class="ts" '
              f'fill="#ffffff" opacity="0.96">{meta["glyph"]} {_esc(meta["label"])}</text>')

            centre[cid] = (bx, bx + bw, by + BAR_H / 2)
            y += ROW_H

    # ---- dependency arrows ----------------------------------------------
    a('<defs><marker id="ah" markerWidth="7" markerHeight="7" refX="6" refY="3" '
      f'orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="{MUTED}"/></marker></defs>')
    by_id = {c["id"]: c for c in chunks}
    for c in chunks:
        cid = c["id"]
        for dep in c.get("depends_on") or []:
            if dep not in centre or cid not in centre:
                continue
            _, dx_end, dy = centre[dep]
            sx, _, sy = centre[cid]
            mx = dx_end + max(10, (sx - dx_end) / 2)
            heavy = cid in crit and dep in crit
            a(f'<path d="M{dx_end},{dy} H{mx} V{sy} H{sx - 3}" fill="none" '
              f'stroke="{MUTED}" stroke-width="{1.6 if heavy else 1}" '
              f'opacity="{0.85 if heavy else 0.45}" marker-end="url(#ah)"/>')

    # ---- legend ----------------------------------------------------------
    ly = y0 + rows * ROW_H + 30
    lx = PAD
    for st in STATUS_ORDER:
        meta = STATUS[st]
        a(f'<rect x="{lx}" y="{ly - 9}" width="11" height="11" rx="2.5" class="bar-{st}"/>')
        a(f'<text x="{lx + 17}" y="{ly}" class="ts ink2">'
          f'{meta["glyph"]} {_esc(meta["label"])}</text>')
        lx += 20 + len(meta["label"]) * 6.2 + 26
    a(f'<text x="{lx + 6}" y="{ly}" class="ts mut">'
      f'outlined bars = critical path</text>')

    a("</svg>")
    return "\n".join(o)


# ---------------------------------------------------------------------------
# The scope document — what the human actually reviews
#
# The chart shows the shape of the work; this shows what each chunk *is*, and
# it deliberately carries no status. Status changes several times a session
# and scope changes when the project changes, so keeping them in separate
# files is what lets the plan review stay signed off through a week of ordinary
# progress and go stale the moment the work itself is redefined.
# ---------------------------------------------------------------------------
def render_scope(plan: dict, placed: dict, total: int, crit: set[str]) -> str:
    chunks = plan["chunks"]
    o = [f'# Plan — {plan.get("project", "project")}', "",
         "What work exists, what each piece is, and what has to happen first.",
         "**Statuses are deliberately not in this file** — see the chart in the "
         "README for those. This is the scope, and it is what the plan review "
         "signs off.", ""]

    discs = plan.get("disciplines") or sorted(
        {c.get("discipline", "general") for c in chunks})
    o += [f'{len(chunks)} chunks · {total} sessions on the critical path · '
          f'disciplines: {", ".join(discs)}', "",
          "![dependency chart](plan.svg)", "",
          "## The work", ""]

    order: list[str] = []
    groups: dict[str, list] = {}
    for c in chunks:
        d = c.get("discipline", "general")
        if d not in order:
            order.append(d)
            groups[d] = []
        groups[d].append(c)

    for disc in order:
        o += [f"### {disc}", ""]
        for c in groups[disc]:
            cid = c["id"]
            est = int(c.get("estimate_sessions", 1))
            head = f'#### {cid} — {c.get("title", "")}'
            if cid in crit:
                head += "  *(critical path)*"
            o += [head, ""]
            if c.get("description") or c.get("notes"):
                o += [str(c.get("description") or c.get("notes")).strip(), ""]
            deps = c.get("depends_on") or []
            bullets = [f'**Needs first:** {", ".join(deps) if deps else "nothing"}',
                       f'**Estimate:** {est} session' + ("s" if est != 1 else "")]
            if c.get("outputs"):
                bullets.append("**Produces:** "
                               + ", ".join(f'`{x}`' for x in c["outputs"]))
            if c.get("review"):
                bullets.append(f'**Human review:** `{c["review"]}` must be '
                               f'signed off before this chunk can be done')
            o += [f"* {b}" for b in bullets]
            o.append("")

    o += ["## What we are asking you", "",
          "1. **Is this all the work?** Test, documentation and manufacturing "
          "are the ones that get left out.",
          "2. **Is the order right?** You may know a constraint we do not — a "
          "part already on the shelf, a lead time, a review that has to pass.",
          "3. **Is any chunk the wrong size?** One chunk is about one working "
          "session; a chunk that is really three should be split now.", "",
          "---", "",
          "<sub>Generated by `plan-render` from `plan.yaml`. Edit the plan, "
          "not this file.</sub>", ""]
    return "\n".join(o)


# ---------------------------------------------------------------------------
# draw.io emitter — the editable dependency chart
#
# The SVG is the review image and it renders inline on github.com, which is
# where the human actually looks. This is the same schedule as a draggable
# graph, for the conversation where a dependency is wrong and the fastest way
# to say so is to move an arrow.
# ---------------------------------------------------------------------------
DIO_W, DIO_H = 210, 62
DIO_COL, DIO_ROW = 300, 84


def _dstyle(**kw) -> str:
    return ";".join(f"{k.replace('_', '')}={v}" for k, v in kw.items()) + ";"


def render_drawio(plan: dict, placed: dict, total: int, crit: set[str]) -> str:
    chunks = plan["chunks"]
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

    done = sum(1 for c in chunks if c.get("status") == "done")
    vertex("title", plan.get("project", "Project plan"),
           _dstyle(text=1, html=1, fillColor="none", strokeColor="none",
                   align="left", verticalAlign="middle", fontSize=16,
                   fontColor=INK["light"], fontStyle=1), PAD, 14, 520, 20)
    vertex("subtitle",
           f'{done}/{len(chunks)} chunks complete · {total} sessions on the '
           f'critical path · generated from plan.yaml',
           _dstyle(text=1, html=1, fillColor="none", strokeColor="none",
                   align="left", verticalAlign="middle", fontSize=10,
                   fontColor=MUTED), PAD, 38, 620, 18)

    # One column per session-start, one row per chunk within that column, so
    # the left-to-right axis is still the schedule.
    lanes: dict[int, int] = {}
    pos: dict[str, tuple[float, float]] = {}
    for c in chunks:
        cid = c["id"]
        start, span = placed[cid]
        row = lanes.get(start, 0)
        lanes[start] = row + 1
        pos[cid] = (PAD + start * DIO_COL, HEADER_H + row * DIO_ROW)

    for c in chunks:
        cid = c["id"]
        st = c.get("status", "todo")
        meta = STATUS.get(st, STATUS["todo"])
        x, y = pos[cid]
        est = int(c.get("estimate_sessions", 1))
        foot = [c.get("discipline", "general"),
                f'{est} session' + ("s" if est != 1 else "")]
        if c.get("review"):
            foot.append(f'review: {c["review"]}')
        value = (f'<b>{html.escape(cid)}</b> · {html.escape(c.get("title", ""))}'
                 f'<br/><font color="{meta["light"]}">{meta["glyph"]} '
                 f'{meta["label"]}</font>'
                 f'<font color="{MUTED}" style="font-size:9px">  ·  '
                 f'{html.escape(" · ".join(foot))}</font>')
        vertex(cid, value,
               _dstyle(rounded=1, whiteSpace="wrap", html=1, fillColor="#ffffff",
                       strokeColor=meta["light"],
                       strokeWidth=3 if cid in crit else 1,
                       align="left", spacingLeft=8, verticalAlign="middle",
                       fontSize=11, arcSize=8),
               x, y, DIO_W, DIO_H)

    for c in chunks:
        for dep in c.get("depends_on") or []:
            if dep not in pos:
                continue
            heavy = c["id"] in crit and dep in crit
            edge(f'{dep}--{c["id"]}',
                 _dstyle(edgeStyle="orthogonalEdgeStyle", rounded=1, html=1,
                         strokeColor="#52514e" if heavy else MUTED,
                         strokeWidth=2 if heavy else 1,
                         endArrow="block", endSize=6,
                         exitX=1, exitY=0.5, entryX=0, entryY=0.5),
                 dep, c["id"])

    width = int(PAD * 2 + max(total, 1) * DIO_COL)
    height = int(HEADER_H + max(lanes.values(), default=1) * DIO_ROW + PAD)
    body = "\n".join(cells)
    return (
        f'<mxfile host="MakeHardware" type="device">\n'
        f'  <diagram name="Project plan" id="project-plan">\n'
        f'    <mxGraphModel dx="{width}" dy="{height}" grid="1" gridSize="10" '
        f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
        f'pageScale="1" pageWidth="{width}" pageHeight="{height}" math="0" '
        f'shadow="0">\n'
        f'      <root>\n'
        f'        <mxCell id="0"/>\n'
        f'        <mxCell id="1" parent="0"/>\n'
        f'{body}\n'
        f'      </root>\n'
        f'    </mxGraphModel>\n'
        f'  </diagram>\n'
        f'</mxfile>\n')


# ---------------------------------------------------------------------------
# README injection
# ---------------------------------------------------------------------------
BEGIN, END = "<!-- PLAN:BEGIN -->", "<!-- PLAN:END -->"


def inject(readme: str, svg_rel: str, plan: dict, total: int,
           drawio_rel: str | None = None) -> bool:
    if not os.path.exists(readme):
        return False
    text = open(readme).read()
    if BEGIN not in text or END not in text:
        return False
    chunks = plan["chunks"]
    done = sum(1 for c in chunks if c.get("status") == "done")
    block = (
        f"{BEGIN}\n"
        f"<!-- generated by plan_render.py — edit plan.yaml, not this block -->\n\n"
        f"![Project plan]({svg_rel})\n\n"
        f"**{done}/{len(chunks)} chunks complete** · "
        f"{total} sessions on the critical path"
        + (f" · [editable version]({drawio_rel})\n\n" if drawio_rel else "\n\n")
        + f"{END}"
    )
    start = text.index(BEGIN)
    stop = text.index(END) + len(END)
    open(readme, "w").write(text[:start] + block + text[stop:])
    return True


def summary(plan: dict, placed: dict, total: int, crit: set[str]) -> None:
    chunks = plan["chunks"]
    print(f"{plan.get('project', 'Project')} — {len(chunks)} chunks, "
          f"{total} sessions on the critical path\n")
    for st in STATUS_ORDER:
        sel = [c for c in chunks if c.get("status") == st]
        if not sel:
            continue
        print(f"  {STATUS[st]['glyph']} {STATUS[st]['label']} ({len(sel)}):")
        for c in sel:
            mark = "*" if c["id"] in crit else " "
            print(f"    {mark} {c['id']:<6} {c.get('title', '')}")
        print()
    ready = [c for c in chunks
             if c.get("status") == "todo"
             and all(next((d for d in chunks if d["id"] == dep), {}).get("status") == "done"
                     for dep in (c.get("depends_on") or []))]
    if ready:
        print("  Ready to start now (dependencies met):")
        for c in ready:
            print(f"    - {c['id']}: {c.get('title', '')}")
        print()

    # Reviews the human still owes an answer on. These block a chunk from
    # being done, so they belong in the status report rather than only in the
    # gate's failure output.
    ledger = plan.get("review_ledger", "docs/review/reviews.yaml")
    waiting = []
    for c in chunks:
        rv = review_state(c, ledger)
        if rv and rv[0] != "approved":
            waiting.append((c, rv))
    if waiting:
        print("  Waiting on human review:")
        for c, (st, detail) in waiting:
            print(f'    - {c["id"]}: review {c["review"]!r} is {st}'
                  + (f" ({detail})" if detail else ""))
        print()

    print("  * = on the critical path")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", nargs="?", default="plan.yaml")
    ap.add_argument("--out", default="docs/plan.svg")
    ap.add_argument("--drawio", default="docs/plan.drawio",
                    help="editable dependency chart; --drawio '' to skip")
    ap.add_argument("--scope", default="docs/plan.md",
                    help="status-free scope document — the thing the plan "
                         "review signs off; --scope '' to skip")
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--summary", action="store_true", help="text status only")
    args = ap.parse_args()

    plan = load(args.plan)
    errors = validate(plan)
    if errors:
        sys.stderr.write("Plan is not valid:\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1
    if args.check:
        print(f"{args.plan}: valid ({len(plan['chunks'])} chunks)")
        return 0

    placed, total = schedule(plan)
    crit = critical_path(plan, placed)

    if args.summary:
        summary(plan, placed, total, crit)
        return 0

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(render_svg(plan, placed, total, crit))
    print(f"wrote {args.out}")

    if args.scope:
        os.makedirs(os.path.dirname(args.scope) or ".", exist_ok=True)
        with open(args.scope, "w") as fh:
            fh.write(render_scope(plan, placed, total, crit))
        print(f"wrote {args.scope}")

    drawio_rel = None
    if args.drawio:
        os.makedirs(os.path.dirname(args.drawio) or ".", exist_ok=True)
        with open(args.drawio, "w") as fh:
            fh.write(render_drawio(plan, placed, total, crit))
        print(f"wrote {args.drawio}")
        drawio_rel = os.path.relpath(
            args.drawio, os.path.dirname(os.path.abspath(args.readme)))

    rel = os.path.relpath(args.out, os.path.dirname(os.path.abspath(args.readme)))
    if inject(args.readme, rel, plan, total, drawio_rel):
        print(f"updated {args.readme}")
    else:
        print(f"note: {args.readme} has no {BEGIN} / {END} markers — chart not embedded")
    summary(plan, placed, total, crit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
