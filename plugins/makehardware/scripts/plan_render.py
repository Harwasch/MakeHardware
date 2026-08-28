#!/usr/bin/env python3
"""Validate a project plan and render it as a dependency Gantt chart.

The plan is the agreement about what work exists, in what order, and what is
done. Each chunk is sized to roughly one AI session, so the horizontal axis is
sessions, not calendar time — which is the honest unit here, because nobody
knows how many wall-clock days a session will take.

    plan_render.py                      # validate, render SVG, update README
    plan_render.py --check              # validate only; exit 1 if the plan is broken
    plan_render.py --summary            # text status, no files written

Chunks are scheduled by longest-path: a chunk starts as soon as every chunk it
depends on has finished. That makes the critical path fall out of the data
rather than being asserted, and it is drawn heavier than the rest.
"""
from __future__ import annotations

import argparse
import html
import os
import sys

import yaml

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
# README injection
# ---------------------------------------------------------------------------
BEGIN, END = "<!-- PLAN:BEGIN -->", "<!-- PLAN:END -->"


def inject(readme: str, svg_rel: str, plan: dict, total: int) -> bool:
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
        f"{total} sessions on the critical path\n\n"
        f"{END}"
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
    print("\n  * = on the critical path")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", nargs="?", default="plan.yaml")
    ap.add_argument("--out", default="docs/plan.svg")
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

    rel = os.path.relpath(args.out, os.path.dirname(os.path.abspath(args.readme)))
    if inject(args.readme, rel, plan, total):
        print(f"updated {args.readme}")
    else:
        print(f"note: {args.readme} has no {BEGIN} / {END} markers — chart not embedded")
    summary(plan, placed, total, crit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
