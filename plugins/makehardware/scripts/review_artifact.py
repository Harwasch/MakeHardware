#!/usr/bin/env python3
"""Build the project review page — one tabbed HTML file, generated from the repo.

The review packets under `docs/review/` are what a human reads on github.com.
This is the other surface: a single page, published as a Claude Artifact, that
accumulates one tab per phase as the project advances and carries the whole
project by the end of it. Artifacts take anchored comments, which is a better
review instrument than a paragraph in a chat log, and the comments come back to
the agent.

**Nothing here is typed by hand.** Every number, table, diagram and status is
read from the file that owns it — `plan.yaml`, `hw/block-diagram.yaml`, the
requirements export, `docs/review/reviews.yaml`, the SVGs already on disk. That
is the same rule the rest of the toolbox follows, and for the same reason: the
most-read document in a project must not be the one nothing can check. The only
prose that comes from a person is the framing — the summary and the questions —
and that is stored in `reviews.yaml`, so it regenerates identically.

Phases are **pinned**, not live. A tab shows the artefacts as they stood at the
commit the human was asked about, because a sign-off against a moving target is
not a sign-off. `review-gate`'s digests are what detect drift; this page reports
it.

    review-artifact                       # write docs/review/artifact.html
    review-artifact --project examples/thermal-probe
    review-artifact --title "Thermal Probe"

Per-project customisation lives in `docs/review/artifact.yaml` — extra tabs,
extra artefacts, reordering. See ARTIFACT_YAML_DOC below.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import html
import json
import os
import urllib.parse
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import review_gate  # noqa: E402  — the ledger and the git helpers

try:
    import plan_render
except Exception:                                     # pragma: no cover
    plan_render = None
try:
    import block_diagram
except Exception:                                     # pragma: no cover
    block_diagram = None
try:
    import req_trace
except Exception:                                     # pragma: no cover
    req_trace = None


ARTIFACT_YAML_DOC = """\
# docs/review/artifact.yaml — per-project shape for the review page.
#
# Every field is optional. Without this file the standard phases are built from
# whatever exists in the repo, which is the right answer for most projects.
#
# title: Thermal Probe                 # defaults to plan.yaml's project name
# subtitle: Walk-in freezer logger     # one line under the title block
# phases:                              # add to, or override, the standard set
#   - id: schematic
#     title: Schematic
#     after: architecture              # where it sits in the tab bar
#     images: [docs/design/schematic/sheet-1.svg]
#     docs:   [docs/design/adr-0002-power.md]
#     tables:
#       - title: ERC
#         csv: docs/design/erc-summary.csv
# hide: [simulation]                   # standard phases to leave out
"""

# Images small enough to inline as a data URI without wrecking the page.
RASTER_BUDGET = 220 * 1024

# SVG is inlined as markup, so it costs no base64 overhead and stays crisp —
# but it is not free, and a plotter hands you something far bigger than any
# hand-written diagram. KiCad's SVG exporter emits one <path> per *line
# segment*, including every stroke of every character of text, so a real sheet
# is enormous: `kicad-cli sch export svg` on KiCad's own pic_programmer demo
# gives 3.0 MB / 61,681 nodes for the root sheet and 1.0 MB / 21,265 for the
# sub-sheet. That is not a pathological case; that is one ordinary A4 sheet.
#
# Measured in headless Chromium on this container, inlined and laid out:
#
#     1.0 MB / 21k nodes   1.04 s
#     3.0 MB / 62k nodes   2.27 s
#
# So render time is not what should decide this. A 1 MB schematic sheet *is*
# worth inlining — showing the schematic is the entire point of the schematic
# tab, and refusing at 500 kB (as this first did) makes the tab useless for
# every real KiCad project. What actually bites is the 16 MB artifact cap, and
# it bites in aggregate: any one sheet fits, six of them do not.
#
# Hence two limits. A per-file one that only catches the genuinely pathological
# and keeps the slowest tab near a couple of seconds, and a running total for
# the page as a whole. Exceeding either is reported the same way an oversized
# raster is — visibly, with the fix named — never silently dropped.
SVG_BUDGET = 1_500 * 1024
SVG_NODE_BUDGET = 30_000
PAGE_INLINE_BUDGET = 9 * 1024 * 1024

# Bytes inlined so far this run. Reset by main(); see spend().
_inlined = 0


def spend(n: int) -> bool:
    """Book `n` bytes against the page budget. False when there is no room."""
    global _inlined
    if _inlined + n > PAGE_INLINE_BUDGET:
        return False
    _inlined += n
    return True

STATE_LABEL = {
    "approved":          ("Approved", "ok"),
    "requested":         ("Awaiting your review", "wait"),
    "changes_requested": ("Changes requested", "stop"),
    "stale":             ("Needs another look", "stop"),
    "none":              ("Not yet submitted", "idle"),
}

PLAN_STATUS = {
    "done":        ("Done", "ok"),
    "in_progress": ("In progress", "wait"),
    "blocked":     ("Blocked", "stop"),
    "todo":        ("To do", "idle"),
}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# Set once from the project root, so a figure that cannot be embedded can still
# point at where the file does render.
REPO: dict[str, str | None] = {"slug": None, "ref": None}


def blob_url(path: str) -> str | None:
    if not REPO["slug"]:
        return None
    return (f'https://github.com/{REPO["slug"]}/blob/{REPO["ref"]}/'
            f'{path.lstrip("/")}')


def drawio_url(path: str) -> str | None:
    """Open a `.drawio` straight in the draw.io editor, from its raw URL.

    diagrams.net takes a `?url=` and fetches the file itself, so this is one
    click to an editable diagram — no download, no import step, and no
    application to install. Better than handing someone a file, which is why
    it sits beside every `.drawio` on the page rather than replacing the link
    to the file itself.

    It fetches anonymously, so it works for a public repository and fails for
    a private one. That is why the file link stays: on a private repo the
    human downloads it from GitHub and drops it on the canvas, which is the
    same two steps they would have had anyway.
    """
    if not REPO["slug"] or not path.lower().endswith(".drawio"):
        return None
    raw = (f'https://raw.githubusercontent.com/{REPO["slug"]}/'
           f'{REPO["ref"]}/{path.lstrip("/")}')
    return f"https://app.diagrams.net/?url={urllib.parse.quote(raw, safe='')}"


# ---------------------------------------------------------------------------
# Reading the project
# ---------------------------------------------------------------------------
def read_yaml(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def read_text(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    with open(path, errors="replace") as fh:
        return fh.read()


def _svg_length(value: str) -> float:
    """`297mm`, `1024`, `12.5pt` -> px. Real exporters do not emit bare pixels.

    kicad-cli writes physical page sizes, matplotlib writes points, Inkscape
    writes whatever it was given. Reading the number and ignoring the unit
    turned an A4 schematic into a 297 px thumbnail.
    """
    m = re.match(r"\s*(-?[\d.]+)\s*([a-z%]*)", str(value or ""), re.I)
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2).lower()
    return n * {"": 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "mm": 96 / 25.4,
                "cm": 96 / 2.54, "in": 96.0}.get(unit, 1.0)


def _scope_css(css: str, ns: str) -> str:
    """Prefix every selector with `#ns`, descending into at-rules correctly.

    Splitting on `}` and prefixing whatever looked like a selector was wrong in
    the one place it mattered most: an `@media` block's first rule kept the
    leading `@media (...)` in its prelude, so it was left unscoped while the
    rules after it were scoped and the braces no longer balanced. Every inlined
    diagram's dark-mode rules leaked onto the page and its own light-mode rules
    outranked them, which is why a dark page rendered a light diagram with dark
    boxes in it.

    Themes are also translated, not just scoped. An exported SVG only knows
    `prefers-color-scheme`, but this page's theme can be set explicitly by the
    viewer — so a dark rule is emitted twice: once guarded so an explicit light
    choice beats a dark OS, and once for the explicit dark toggle.
    """
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        prelude = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += (css[k] == "{") - (css[k] == "}")
            k += 1
        body = css[j + 1:k - 1]

        if prelude.startswith("@"):
            if re.match(r"@media\b.*prefers-color-scheme\s*:\s*dark", prelude, re.I):
                inner = _scope_css(body, ns)
                guard = ':root:not([data-theme="light"])'
                out.append("@media (prefers-color-scheme:dark){"
                           + _prefix_each(inner, guard) + "}")
                out.append(_prefix_each(inner, ':root[data-theme="dark"]'))
            elif re.match(r"@(media|supports|container|layer)\b", prelude, re.I):
                out.append(f"{prelude}{{{_scope_css(body, ns)}}}")
            else:
                out.append(f"{prelude}{{{body}}}")     # @font-face, @keyframes
        elif prelude:
            sels = ",".join(f"#{ns} {sel.strip()}"
                            for sel in prelude.split(",") if sel.strip())
            out.append(f"{sels}{{{body}}}")
        i = k
    return "".join(out)


def _prefix_each(css: str, prefix: str) -> str:
    """Put `prefix` in front of every top-level selector in already-scoped CSS."""
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        prelude = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += (css[k] == "{") - (css[k] == "}")
            k += 1
        body = css[j + 1:k - 1]
        sels = ",".join(f"{prefix} {sel.strip()}"
                        for sel in prelude.split(",") if sel.strip())
        out.append(f"{sels}{{{body}}}")
        i = k
    return "".join(out)


def paints_own_sheet(head: str, body: str) -> bool:
    """True when the SVG fills its whole viewport with a light colour.

    The theming story for an inlined SVG is: strokes and fills that the page's
    CSS can reach follow the reader's theme, and everything else does not.
    Plotters put everything in the second category — KiCad writes
    `style="fill:#F5F4EF"` on a `<g>` and a full-page `<rect>` inside it, then
    draws the whole schematic in `#000000`, all inline, all unreachable.

    Recolouring it would be a lie about the artefact, and leaving it alone
    gives a blinding rectangle on a dark page. So detect it and mat it, the
    same treatment an opaque raster gets: the sheet reads as a sheet.
    """
    box = re.search(r'viewBox="\s*[\d.eE+-]+[ ,]+[\d.eE+-]+[ ,]+'
                    r'([\d.eE+-]+)[ ,]+([\d.eE+-]+)', head)
    if not box:
        return False
    try:
        vw, vh = float(box.group(1)), float(box.group(2))
    except ValueError:
        return False
    if vw <= 0 or vh <= 0:
        return False

    for m in re.finditer(r"<rect\b([^>]*)>", body):
        attrs = m.group(1)
        w = re.search(r'\bwidth="([\d.eE+-]+)"', attrs)
        h = re.search(r'\bheight="([\d.eE+-]+)"', attrs)
        if not w or not h:
            continue
        try:
            if float(w.group(1)) < vw * 0.9 or float(h.group(1)) < vh * 0.9:
                continue
        except ValueError:
            continue
        # The fill is usually not on the rect: it is inherited from the <g>
        # the plotter opened just above it. Take the nearest one before here.
        own = re.search(r'\bfill="(#[0-9A-Fa-f]{6})"', attrs)
        if own:
            colour = own.group(1)
        else:
            before = re.findall(r'fill:\s*(#[0-9A-Fa-f]{6})', body[:m.start()])
            if not before:
                continue
            colour = before[-1]
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        if (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.55:
            return True
    return False


def inline_svg(path: str) -> tuple[str | None, float, bool]:
    """SVG goes in as markup: crisp at any zoom, themes with the page, no cap.

    Everything here exists because a real exporter's SVG is not a tidy one:

    * **ids collide.** Several diagrams on one page would otherwise share
      `#ah`, `#ra`, `#glyph0-1` and each other's gradients, and the last one
      defined wins for all of them.
    * **class names collide, in both directions.** kicad-cli and matplotlib
      both ship a `<style>` block, and its selectors are global once inlined.
      Their `.t` or `.h` would restyle this page's text, and this page's would
      restyle theirs. Every rule is therefore scoped to the wrapper.
    * **width is a physical length.** See `_svg_length`.
    * **`<script>` has no business here** and is stripped.

    Returns `(markup, intrinsic_width, paints_own_sheet)`. The third is for
    exporters that fill the whole page with a light colour and then draw in
    black — which is every KiCad plot, and it is done with inline
    `style="fill:#F5F4EF"` on a full-page `<rect>`, so no amount of CSS
    scoping will theme it. Those get matted exactly like an opaque raster:
    honest about what the artefact is, instead of a black-on-black schematic
    or a bright slab with no border.
    """
    text = read_text(path)
    if not text:
        return None, 0.0, False
    text = re.sub(r"<\?xml[^>]*\?>", "", text)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.S | re.I)
    tag = re.search(r"<svg\b[^>]*>", text)
    if not tag:
        return None, 0.0, False

    ns = "g" + hashlib.sha1(path.encode()).hexdigest()[:7]
    for m in set(re.findall(r'\bid="([^"]+)"', text)):
        text = re.sub(rf'\bid="{re.escape(m)}"', f'id="{ns}-{m}"', text)
        text = text.replace(f"url(#{m})", f"url(#{ns}-{m})")
        text = re.sub(rf'(xlink:href|href)="#{re.escape(m)}"',
                      rf'\1="#{ns}-{m}"', text)

    def scope(block: re.Match) -> str:
        return "<style>" + _scope_css(block.group(1), ns) + "</style>"

    text = re.sub(r"<style[^>]*>(.*?)</style>", scope, text, flags=re.S)

    head = tag.group(0)
    # The `width` attribute is the intrinsic size; the viewBox only fixes the
    # user-unit coordinate system and the aspect ratio. Reading them the other
    # way round is wrong whenever the two use different units — and a plotter
    # is exactly that case. KiCad writes `width="297.0022mm"` beside
    # `viewBox="0 0 297.0022 210.0072"`, so preferring the viewBox laid an A4
    # schematic out 297 px wide: a thumbnail of a drawing nobody could read.
    w = re.search(r'\swidth="([^"]+)"', head)
    intrinsic = _svg_length(w.group(1)) if w else 0.0
    if not intrinsic:
        box = re.search(
            r'viewBox="\s*[\d.eE+-]+[ ,]+[\d.eE+-]+[ ,]+([\d.eE+-]+)', head)
        intrinsic = float(box.group(1)) if box else 720.0
    new_head = re.sub(r'\s(width|height)="[^"]*"', "", head)
    if "preserveAspectRatio" not in new_head:
        new_head = new_head[:-1] + ' preserveAspectRatio="xMidYMid meet">'
    body = text.replace(head, new_head, 1).strip()
    # The wrapper is what the scoped selectors hang off.
    return (f'<span id="{ns}" class="svgwrap">{body}</span>', intrinsic,
            paints_own_sheet(head, body))


def png_width(blob: bytes) -> float:
    """Pixel width from the IHDR chunk. No image library needed for this."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR":
        return float(int.from_bytes(blob[16:20], "big"))
    return 0.0


def png_opaque(blob: bytes) -> bool:
    """True when the PNG carries no alpha, so it will paint its own background.

    A raster cannot follow the page's theme. One with alpha composites onto the
    sheet and is fine either way; an opaque one — which is most CAD and board
    renders, since they are exported against white — becomes a bright slab on a
    dark page. Those get a deliberate light mat so they read as a mounted
    photograph rather than a hole in the layout.
    """
    if blob[:8] != b"\x89PNG\r\n\x1a\n" or blob[12:16] != b"IHDR":
        return True
    colour_type = blob[25]
    if colour_type in (4, 6):                    # grey+alpha, RGBA
        return False
    return b"tRNS" not in blob[:4096]


def inline_raster(path: str) -> tuple[str | None, str | None, float, bool]:
    """(data-uri, warning, width, opaque). Big rasters are reported, not embedded."""
    if not os.path.isfile(path):
        return None, None, 0.0, True
    size = os.path.getsize(path)
    if size > RASTER_BUDGET:
        return None, (f"{path} is {size // 1024} kB — too large to embed. "
                      f"Downscale it for review, or link it."), 0.0, True
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp"}.get(
                os.path.splitext(path)[1].lower())
    if not mime:
        return None, None, 0.0, True
    if not spend(size * 4 // 3):                 # base64 costs a third more
        return None, (f"{path} would take this page past its "
                      f"{PAGE_INLINE_BUDGET // (1024 * 1024)} MB inline "
                      f"budget. It is linked instead."), 0.0, True
    with open(path, "rb") as fh:
        blob = fh.read()
    return (f"data:{mime};base64,{base64.b64encode(blob).decode()}", None,
            png_width(blob), png_opaque(blob))


def markdown_to_html(text: str, strip_h1: bool = True) -> str:
    """Enough markdown for what the toolbox writes: headings, tables, lists,
    emphasis, code and images. Not a general parser, deliberately — the input
    is generated by this repo's own tools."""
    out: list[str] = []
    lines = text.splitlines()
    i, in_list, in_table = 0, "", False

    def close():
        nonlocal in_list, in_table
        if in_list:
            out.append(f"</{in_list}>")
            in_list = ""
        if in_table:
            out.append("</tbody></table></div>")
            in_table = False

    def spans(s: str) -> str:
        s = esc(s)
        s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", "", s)          # images: handled apart
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            close()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            close()
            lvl = len(m.group(1))
            if not (strip_h1 and lvl == 1):
                out.append(f"<h{min(lvl + 1, 6)}>{spans(m.group(2))}</h{min(lvl + 1, 6)}>")
            i += 1
            continue
        # Bullets and numbered steps. Ordered lists are not a nicety here:
        # an assembly traveller or a test sequence is a numbered list, and
        # rendering "1. Solder paste ... 2. Place ..." as one run-on paragraph
        # loses the one thing that made it a procedure.
        bullet = ln.lstrip().startswith(("* ", "- "))
        num = re.match(r"\s*\d+[.)]\s+", ln)
        if bullet or num:
            tag = "ul" if bullet else "ol"
            if in_list != tag:
                close()
                out.append(f"<{tag}>")
                in_list = tag
            # An item runs until a blank line, the next item or the next block
            # — the toolbox hard-wraps its markdown at ~76 columns, so most
            # items are two or three lines and treating each wrapped line as a
            # new paragraph shattered every list on the page.
            item = [ln.lstrip()[2:].strip() if bullet
                    else ln[num.end():].strip()]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip() or nxt.lstrip().startswith(("* ", "- ")) \
                        or re.match(r"\s*\d+[.)]\s+", nxt) \
                        or nxt.lstrip()[:1] in ("#", "|", ">") \
                        or nxt.lstrip().startswith("```"):
                    break
                item.append(nxt.strip())
                i += 1
            out.append(f"<li>{spans(' '.join(item))}</li>")
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            close()
            heads = [c.strip() for c in ln.strip().strip("|").split("|")]
            out.append('<div class="scroll"><table><thead><tr>'
                       + "".join(f"<th>{spans(h)}</th>" for h in heads)
                       + "</tr></thead><tbody>")
            in_table = True
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{spans(c)}</td>" for c in cells)
                           + "</tr>")
                i += 1
            close()
            continue
        close()
        # Gather the whole paragraph before touching spans: `**a\nb**` is one
        # emphasis run in markdown, and processing line by line leaves the
        # asterisks on the page.
        para = [ln.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|\s*[*-]\s|\s*\|)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{spans(' '.join(para))}</p>")
    close()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Phase content
# ---------------------------------------------------------------------------
class Phase:
    def __init__(self, pid: str, title: str, eyebrow: str = ""):
        self.id, self.title, self.eyebrow = pid, title, eyebrow
        self.review: dict | None = None
        self.blocks: list[tuple[str, object]] = []
        self.metrics: list[tuple[str, str, str]] = []
        self.notes: list[str] = []

    def add(self, kind: str, payload) -> None:
        if payload:
            self.blocks.append((kind, payload))

    @property
    def state(self) -> str:
        return review_gate.state(self.review) if self.review else "none"


VIEWER = {".pdf": "GitHub's PDF viewer", ".stl": "GitHub's 3D viewer",
          ".step": "any CAD package", ".stp": "any CAD package",
          ".kicad_sch": "KiCad", ".kicad_pcb": "KiCad",
          ".drawio": "draw.io", ".csv": "GitHub's table view"}


def svg_too_heavy(full: str) -> str | None:
    """Why this SVG must not be inlined, or None if it is fine to inline.

    A hand-written diagram is a few kB. A plotted one is not: KiCad emits one
    <path> per stroked segment, so a dense schematic sheet arrives as megabytes
    of markup and tens of thousands of nodes. Inlining it would push the page
    toward the artifact cap and hand the browser a DOM it cannot lay out
    smoothly, so it is reported instead — with the fix, because "too big" on
    its own tells the agent nothing it can act on.
    """
    size = os.path.getsize(full)
    rel = os.path.basename(full)
    advice = ("It still renders on GitHub, so it is linked rather than shown. "
              "Plot fewer sheets, or a simplified one, for the review — and "
              "export a PDF alongside them for the record.")

    if size > SVG_BUDGET:
        return (f"{rel} is {size // 1024} kB, past the {SVG_BUDGET // 1024} kB "
                f"limit for one figure. {advice}")
    with open(full, "r", errors="replace") as fh:
        nodes = fh.read().count("<")
    if nodes > SVG_NODE_BUDGET:
        return (f"{rel} holds {nodes:,} elements, past the "
                f"{SVG_NODE_BUDGET:,} limit for one figure — enough to make "
                f"its tab visibly slow to open. {advice}")
    if not spend(size):
        return (f"{rel} would take this page past its "
                f"{PAGE_INLINE_BUDGET // (1024 * 1024)} MB inline budget, "
                f"which exists so the whole page stays inside the 16 MB "
                f"artifact cap. {advice}")
    return None

# Where a diagram's editable source lives relative to its render. The two are
# not always siblings: `block-diagram` writes `hw/block-diagram.drawio` and
# `docs/design/block-diagram.svg`, so a same-directory lookup found the plan
# and the requirements map and missed the block diagram — the one people most
# want to open, because it is the one they argue with.
DRAWIO_DIRS = ["", "hw", "docs/design", "docs"]


def find_editable(root: str, path: str) -> str | None:
    """The `.drawio` a rendered diagram was generated from, if there is one."""
    if path.lower().endswith(".drawio"):
        return None
    stem = os.path.basename(os.path.splitext(path)[0])
    seen = []
    for d in [os.path.dirname(path)] + DRAWIO_DIRS:
        cand = os.path.normpath(os.path.join(d, stem + ".drawio"))
        if cand in seen:
            continue
        seen.append(cand)
        if os.path.exists(os.path.join(root, cand)):
            return cand
    return None


def figure(root: str, path: str, caption: str = "") -> dict | None:
    """A figure, or an honest note about why there isn't one.

    Never returns None for a path someone asked for. Silently dropping a
    figure is the worst behaviour available here: the agent lists an artefact,
    the export failed or produced something unembeddable, and the review page
    just does not mention it — so the human reviews a page with a hole in it
    and nobody knows.
    """
    full = os.path.join(root, path)
    ext = os.path.splitext(path)[1].lower()

    # A rendered diagram is for reading; the `.drawio` beside it is for
    # disagreeing with. Offer it at the picture, not in a list further down
    # the page — the moment someone wants to move a block is the moment they
    # are looking at the block.
    editable = find_editable(root, path)

    if not os.path.exists(full):
        return {"warn": f"{path} does not exist. The export that should have "
                        f"produced it did not run, or failed.",
                "caption": caption, "path": path}

    if ext == ".svg":
        heavy = svg_too_heavy(full)
        if heavy:
            return {"warn": heavy, "link": True, "caption": caption,
                    "path": path}
        svg, width, sheet = inline_svg(full)
        if svg:
            return {"svg": svg, "caption": caption, "path": path, "w": width,
                    "mat": sheet, "editable": editable}
        return {"warn": f"{path} is not readable as SVG.",
                "caption": caption, "path": path}

    uri, warn, rw, opaque = inline_raster(full)
    if uri:
        return {"uri": uri, "caption": caption, "path": path, "w": rw,
                "mat": opaque, "editable": editable}
    if warn:
        return {"warn": warn, "caption": caption, "path": path}

    where = VIEWER.get(ext)
    if where:
        return {"warn": f"{path} cannot be embedded in this page — open it on "
                        f"GitHub, where it renders in {where}." if ext in
                        (".pdf", ".stl", ".csv") else
                        f"{path} cannot be embedded in this page; it needs "
                        f"{where}. Export an SVG or a PNG for review.",
                "link": True, "caption": caption, "path": path}
    return {"warn": f"{path} is a {ext or 'file'} — nothing on this page can "
                    f"show it. Export an SVG or a PNG.",
            "caption": caption, "path": path}


def add_sources(root: str, p: "Phase", specs: list[tuple[str, str, str]]) -> None:
    """Offer the editable originals behind a phase's pictures.

    The page shows an SVG because that is what renders in a browser. The file
    the human actually wants when they disagree with the picture is the one
    they can open and change — the `.drawio`, the `.kicad_sch`, the `.step` —
    and until this existed the page rendered `block-diagram.svg` without ever
    mentioning that `block-diagram.drawio` sat beside it in the repo.

    Only files that exist are listed: a project with no `.drawio` should not be
    shown a dead link to one.
    """
    links = [{"label": label, "path": path, "why": why, "group": "",
              "url": blob_url(path), "drawio": drawio_url(path),
              "missing": False}
             for path, label, why in specs
             if os.path.exists(os.path.join(root, path))]
    if links:
        p.add("links", {"title": "The editable originals", "note": None,
                        "rows": links})


def phase_vision(root: str) -> Phase | None:
    doc = read_text(os.path.join(root, "docs/design/vision.md"))
    vdir = os.path.join(root, "docs/design/vision")
    if not doc and not os.path.isdir(vdir):
        return None
    p = Phase("vision", "Vision", "Stage 1")
    if doc:
        p.add("prose", markdown_to_html(doc))
    figs = []
    for stem in sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []:
        d = os.path.join(vdir, stem)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".svg", ".png", ".jpg", ".jpeg")):
                fig = figure(root, os.path.relpath(os.path.join(d, f), root),
                             f"{stem.replace('_', ' ')} — {os.path.splitext(f)[0]}")
                if fig:
                    figs.append(fig)
    p.add("figures", figs)
    return p


def phase_plan(root: str) -> Phase | None:
    plan = read_yaml(os.path.join(root, "plan.yaml"))
    if not plan or not plan.get("chunks"):
        return None
    p = Phase("plan", "Plan", "Stage 2")
    chunks = plan["chunks"]
    counts = {k: sum(1 for c in chunks if c.get("status") == k) for k in PLAN_STATUS}
    total = len(chunks)
    sessions = "—"
    crit: set = set()
    if plan_render:
        placed, span = plan_render.schedule(plan)
        crit = plan_render.critical_path(plan, placed)
        sessions = str(span)
    p.metrics = [
        (str(total), "chunks", ""),
        (f'{counts["done"]}', "done", f'{round(100 * counts["done"] / total)}% complete'),
        (sessions, "sessions", "on the critical path"),
        (f'{counts["blocked"]}', "blocked", "" if counts["blocked"] else "nothing stuck"),
    ]
    p.add("figures", [f for f in [figure(
        root, "docs/plan.svg",
        "Dependency chart — one column per session, scheduled by longest "
        "path. Outlined bars are the critical path.")] if f])

    rows = []
    for c in chunks:
        label, tone = PLAN_STATUS.get(c.get("status", "todo"), PLAN_STATUS["todo"])
        deps = ", ".join(c.get("depends_on") or []) or "—"
        rows.append({
            "cells": [c.get("id", ""), c.get("title", ""),
                      c.get("discipline", ""), deps,
                      str(c.get("estimate_sessions", 1))],
            "tone": tone, "state": label,
            "crit": c.get("id") in crit,
            "detail": c.get("description") or c.get("notes") or "",
            "outputs": c.get("outputs") or [],
            "review": c.get("review"),
        })
    p.add("chunks", {"headers": ["Chunk", "Title", "Discipline", "Needs first", "Est."],
                     "rows": rows, "detail_col": 1})
    if plan_render:
        claims = plan_render.check_claims(plan)
        p.notes = claims
    add_sources(root, p, [
        ('docs/plan.drawio', 'Plan chart (draw.io)',
         'Opens in draw.io or diagrams.net — move a bar to re-plan'),
        ('plan.yaml', 'Plan source',
         'What both charts are generated from'),
    ])
    return p

def phase_requirements(root: str) -> Phase | None:
    reqs, summary, findings = None, None, None

    # Live strictdoc wins. The cached export is the fallback for an environment
    # without it — reading the cache first would let a stale snapshot shadow
    # the real tree, which is exactly the drift this toolbox exists to stop.
    if req_trace and os.path.isdir(os.path.join(root, "requirements")):
        cwd = os.getcwd()
        try:
            os.chdir(root)
            reqs = req_trace.load("requirements")
            a = req_trace.analyse(reqs)
            summary = {k: a[k] for k in ("total", "verified", "with_evidence",
                                         "coverage_pct", "by_level")}
            findings = a["findings"]
        except (SystemExit, OSError, ValueError):
            reqs = None
        finally:
            os.chdir(cwd)

    if not reqs:
        cached = read_text(os.path.join(root, "docs/design/requirements.json"))
        if cached:
            data = json.loads(cached)
            reqs, summary, findings = (data.get("requirements"),
                                       data.get("summary"), data.get("findings"))
    if not reqs:
        return None

    p = Phase("requirements", "Requirements", "Stage 3")
    gaps = sum(len(v) for v in (findings or {}).values())
    p.metrics = [
        (str(summary["total"]), "requirements", ""),
        (str(summary["verified"]), "verified", ""),
        (f'{summary["coverage_pct"]}%', "with evidence", ""),
        (str(gaps), "gaps", "the gate is failing on" if gaps else "clean"),
    ]
    p.add("figures", [f for f in [figure(
        root, "docs/design/requirements-map.svg",
        "Requirement tree — an arrow points from a requirement to the one "
        "that refines it. Red borders are gaps the gate is failing on.")] if f])

    rows = []
    for r in reqs:
        tone = {"Verified": "ok", "Implemented": "wait", "Agreed": "wait",
                "Waived": "idle"}.get(r.get("status", ""), "idle")
        rows.append({"cells": [r.get("uid", ""), r.get("title", ""),
                               r.get("verification", ""),
                               r.get("budget", "") or "—",
                               ", ".join(r.get("parents") or []) or "—"],
                     "tone": tone, "state": r.get("status", ""),
                     "detail": "", "outputs": r.get("files") or [], "crit": False,
                     "review": None})
    p.add("chunks", {"headers": ["UID", "Requirement", "Method", "Budget", "Refines"],
                     "rows": rows, "detail_col": 1})
    for kind, items in (findings or {}).items():
        p.notes.extend(items)
    add_sources(root, p, [
        ('docs/design/requirements-map.drawio', 'Requirements map (draw.io)',
         'Opens in draw.io or diagrams.net'),
    ])
    return p

def phase_architecture(root: str) -> Phase | None:
    spec = read_yaml(os.path.join(root, "hw/block-diagram.yaml"))
    if not spec or not spec.get("blocks"):
        return None
    p = Phase("architecture", "Architecture", "Stage 4")
    p.add("figures", [f for f in [figure(
        root, "docs/design/block-diagram.svg",
        "Power tree with a budget gauge per rail, then the functional "
        "blocks and the buses between them.")] if f])

    if block_diagram:
        rows = block_diagram.budget(spec)
        tight = [r for r in rows if r.get("tight")]
        over = [r for r in rows if r.get("over")]
        p.metrics = [
            (str(len(spec["blocks"])), "blocks", ""),
            (str(len(rows)), "rails", ""),
            (str(len(spec.get("buses") or [])), "buses", ""),
            (str(len(over) or len(tight)),
             "rails over budget" if over else "rails tight",
             "" if over else "within 20% of the limit"),
        ]
        brows = []
        for r in rows:
            limit = r["limit"]
            pct = f'{100 * r["max"] / limit:.0f}%' if limit else "—"
            tone = "stop" if r["over"] else ("wait" if r["tight"] else "ok")
            head = max(r["loads"], key=lambda l: l[3])[0] if r["loads"] else "—"
            brows.append({
                "cells": [r["id"], f'{r["voltage"]} V',
                          block_diagram._amps(r["typ"]),
                          block_diagram._amps(r["max"]),
                          block_diagram._amps(limit) if limit else "—", pct,
                          head],
                "tone": tone,
                "state": "over budget" if r["over"] else ("tight" if r["tight"] else "ok"),
                "detail": "", "outputs": [], "crit": False, "review": None,
            })
        # No detail column: a power budget is numbers, and the rail's notes
        # belong in the spec and the summary, not wrapped inside a cell.
        p.add("chunks", {"headers": ["Rail", "V", "Typ", "Max", "Limit",
                                     "Used", "Largest load"],
                         "rows": brows, "detail_col": None})
        _errors, warnings = block_diagram.validate(spec)
        p.notes = warnings
    add_sources(root, p, [
        ('hw/block-diagram.drawio', 'Block diagram (draw.io)',
         'Opens in draw.io or diagrams.net — drag the file onto the canvas'),
        ('hw/block-diagram.yaml', 'Block diagram source',
         'The spec both files are generated from'),
    ])
    return p

def _humanise(path: str) -> str:
    """`sheet-1-power.svg` -> `Sheet 1 power`. Better than shouting the filename."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.replace("-", " ").replace("_", " ").strip().capitalize()


def read_csv(path: str) -> tuple[list[str], list[list[str]]] | None:
    text = read_text(path)
    if not text:
        return None
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return None
    return rows[0], rows[1:]


# A price that nobody checked is a guess wearing a number's clothes, and a BOM
# is where that does real damage. A row is treated as verified only if it says
# so; everything else is called out on the page rather than passed off.
VERIFIED = re.compile(r"quoted|in stock|stock:|confirmed|verified|po |invoice",
                      re.I)
ESTIMATE = re.compile(r"estimate|est\.|approx|assumed|guess|tbd|unknown", re.I)


def phase_from_config(root: str, cfg: dict) -> Phase | None:
    p = Phase(cfg["id"], cfg.get("title", cfg["id"].title()), cfg.get("eyebrow", ""))
    figs = []
    captions = cfg.get("captions") or {}
    for path in cfg.get("images") or []:
        cap = captions.get(path) or _humanise(path)
        fig = figure(root, path, cap)
        if fig:
            figs.append(fig)
    p.add("figures", figs)

    for path in cfg.get("docs") or []:
        text = read_text(os.path.join(root, path))
        if text:
            p.add("prose", markdown_to_html(text))
        else:
            p.notes.append(f"{path} is listed for this phase but does not exist.")

    for spec in cfg.get("tables") or []:
        path = spec.get("csv")
        data = read_csv(os.path.join(root, path)) if path else None
        if not data:
            p.notes.append(f"{path} is listed for this phase but could not be read.")
            continue
        headers, rows = data
        basis_col = next((i for i, h in enumerate(headers)
                          if h.strip().lower() in ("basis", "source", "price basis")),
                         None)
        estimated = 0
        marked = []
        for r in rows:
            tone = ""
            if basis_col is not None and basis_col < len(r):
                cell = r[basis_col]
                if ESTIMATE.search(cell):
                    tone, estimated = "stop", estimated + 1
                elif VERIFIED.search(cell):
                    tone = "ok"
            marked.append({"cells": r, "tone": tone})
        p.add("csvtable", {"title": spec.get("title") or _humanise(path),
                           "note": spec.get("note"), "headers": headers,
                           "rows": marked, "estimated": estimated,
                           "basis_col": basis_col, "path": path})

    links = []
    for lk in cfg.get("links") or []:
        path = lk.get("path", "")
        links.append({"label": lk.get("label") or _humanise(path),
                      "path": path, "why": lk.get("why", ""),
                      "group": lk.get("group", ""),
                      "url": blob_url(path),
                      "drawio": drawio_url(path),
                      "missing": bool(path) and not os.path.exists(
                          os.path.join(root, path))})
    if links:
        p.add("links", {"title": cfg.get("links_title") or "Documents a run needs",
                        "note": cfg.get("links_note"), "rows": links})

    return p if (p.blocks or cfg.get("always")) else None


STANDARD = [phase_vision, phase_plan, phase_requirements, phase_architecture]


def collect(root: str, cfg: dict) -> list[Phase]:
    hide = set(cfg.get("hide") or [])
    phases = [p for p in (fn(root) for fn in STANDARD) if p and p.id not in hide]
    for extra in cfg.get("phases") or []:
        p = phase_from_config(root, extra)
        if not p or p.id in hide:
            continue
        after = extra.get("after")
        idx = next((i + 1 for i, q in enumerate(phases) if q.id == after), len(phases))
        phases.insert(idx, p)

    ledger = review_gate.load(os.path.join(root, review_gate.LEDGER))
    for p in phases:
        p.review = review_gate.find(ledger, p.id)
    # A review with no phase of its own still belongs on the page.
    known = {p.id for p in phases}
    for r in ledger.get("reviews", []):
        if r.get("id") not in known and r.get("id") not in hide:
            p = Phase(r["id"], r.get("title", r["id"]).split(",")[0], "")
            p.review = r
            phases.append(p)
    return phases


# ---------------------------------------------------------------------------
# The page
#
# Treated as an instrument, not a document: it is scanned and operated. The
# header is a drawing title block, because that is the vernacular of the
# subject and it encodes real information — project, revision, date, phase,
# state. Colours are the ones plan_render and block_diagram already use, so an
# inlined diagram sits flush on the page rather than looking pasted in.
# ---------------------------------------------------------------------------
CSS = """
:root{
  --ground:#fcfcfb; --panel:#ffffff; --sunk:#f4f3f0;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --rule:#c3c2b7; --rule-soft:#e4e2dc;
  --ok:#0ca30c; --wait:#2a78d6; --stop:#d03b3b; --idle:#898781;
  --accent:#0f9b8e;
  --sans:'IBM Plex Sans',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --cond:'IBM Plex Sans Condensed',var(--sans);
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#1a1a19; --panel:#242422; --sunk:#1f1f1e;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --rule:#383835; --rule-soft:#2c2c2a;
    --ok:#2fbb2f; --wait:#4d93e8; --stop:#e05555; --accent:#25b3a5;
  }
}
:root[data-theme="dark"]{
  --ground:#1a1a19; --panel:#242422; --sunk:#1f1f1e;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --rule:#383835; --rule-soft:#2c2c2a;
  --ok:#2fbb2f; --wait:#4d93e8; --stop:#e05555; --accent:#25b3a5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 72px}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
code{font-family:var(--mono);font-size:0.88em;background:var(--sunk);
  padding:0.1em 0.35em;border-radius:3px}

/* ---- title block: the drawing-sheet header ---- */
.block{border:1px solid var(--rule);background:var(--panel);margin:20px 0 0;
  display:grid;grid-template-columns:1fr;}
.block-main{padding:18px 20px 16px;border-bottom:1px solid var(--rule)}
.block-main h1{font-size:29px;line-height:1.1;margin:0;font-weight:600;
  letter-spacing:-0.015em;text-wrap:balance}
.block-main p{margin:6px 0 0;color:var(--ink-2);font-size:14.5px;max-width:64ch}
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr))}
.field{padding:9px 20px;border-right:1px solid var(--rule-soft);min-width:0}
.field:last-child{border-right:0}
.field .k{font-family:var(--cond);font-size:10px;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--muted);display:block}
.field .v{font-family:var(--mono);font-size:13px;color:var(--ink);
  display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.field .v a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--rule)}
.field .v a:hover{color:var(--accent);border-bottom-color:var(--accent)}

/* ---- outstanding strip ---- */
.strip{border:1px solid var(--rule);border-top:0;background:var(--sunk);
  padding:12px 20px;display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}
.strip .k{font-family:var(--cond);font-size:10px;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--muted)}
.strip p{margin:0;font-size:14px;color:var(--ink-2)}

/* ---- tabs ---- */
.tabs{display:flex;gap:2px;overflow-x:auto;border-bottom:1px solid var(--rule);
  margin-top:24px;scrollbar-width:thin}
.tab{appearance:none;background:none;border:0;border-bottom:2px solid transparent;
  font-family:var(--sans);font-size:14px;font-weight:500;color:var(--ink-2);
  padding:10px 14px 9px;cursor:pointer;white-space:nowrap;display:flex;
  align-items:center;gap:7px}
.tab:hover{color:var(--ink)}
.tab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent);
  font-weight:600}
.tab .dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto}

/* ---- panel ---- */
.panel{padding-top:26px}
.phase-head{display:flex;justify-content:space-between;align-items:flex-start;
  gap:20px;flex-wrap:wrap;margin-bottom:18px}
.phase-head h2{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em}
.eyebrow{font-family:var(--cond);font-size:10.5px;letter-spacing:0.12em;
  text-transform:uppercase;color:var(--muted);display:block;margin-bottom:3px}
.pill{font-family:var(--cond);font-size:11px;letter-spacing:0.07em;
  text-transform:uppercase;padding:4px 10px;border-radius:999px;
  border:1px solid currentColor;white-space:nowrap;font-weight:600}
.t-ok{color:var(--ok)} .t-wait{color:var(--wait)}
.t-stop{color:var(--stop)} .t-idle{color:var(--muted)}
.b-ok{background:var(--ok)} .b-wait{background:var(--wait)}
.b-stop{background:var(--stop)} .b-idle{background:var(--muted)}

.summary{border-left:2px solid var(--accent);padding:2px 0 2px 16px;
  margin:0 0 22px;color:var(--ink-2);max-width:70ch;font-size:15px}

/* ---- metrics ---- */
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  border:1px solid var(--rule);background:var(--panel);margin-bottom:24px}
.metric{padding:14px 18px;border-right:1px solid var(--rule-soft)}
.metric:last-child{border-right:0}
.metric .n{font-family:var(--mono);font-size:25px;font-weight:500;
  font-variant-numeric:tabular-nums;line-height:1.1}
.metric .l{font-family:var(--cond);font-size:10.5px;letter-spacing:0.09em;
  text-transform:uppercase;color:var(--muted);margin-top:4px}
.metric .s{font-size:12px;color:var(--ink-2);margin-top:2px}

/* ---- figure: framed like a drawing sheet ---- */
figure{margin:0 0 24px;min-width:0}
.figgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:20px;align-items:start}
.sheet{border:1px solid var(--rule);background:var(--panel);padding:16px;
  overflow-x:auto}
.sheet.mat{background:#f7f6f3;border-color:var(--rule)}
.sheet .svgwrap{display:block}
.sheet svg{display:block;width:100%;height:auto;max-width:100%}
.sheet img{display:block;max-width:100%;height:auto;margin:0 auto}
figcaption{font-size:12.5px;color:var(--muted);margin-top:8px;max-width:70ch}
.acts{display:block;margin-top:5px;font-size:12px}\n.tally{font-size:12.5px;color:var(--muted);margin:0 0 10px}\ntr.grp td{font-family:var(--cond);font-size:11.5px;letter-spacing:0.09em;text-transform:uppercase;color:var(--muted);padding-top:16px;border-bottom:1px solid var(--rule)}\na.alt{font-size:11.5px;white-space:nowrap;margin-left:8px}
.acts a{margin-right:2px}

/* ---- tables ---- */
.scroll{overflow-x:auto;border:1px solid var(--rule);background:var(--panel);
  margin-bottom:24px}
table{border-collapse:collapse;width:100%;font-size:14px}
th{font-family:var(--cond);font-size:10.5px;letter-spacing:0.09em;
  text-transform:uppercase;color:var(--muted);text-align:left;font-weight:600;
  padding:9px 14px;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:9px 14px;border-bottom:1px solid var(--rule-soft);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td:first-child{font-family:var(--mono);font-size:13px;white-space:nowrap}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap}
.state{font-family:var(--cond);font-size:10.5px;letter-spacing:0.06em;
  text-transform:uppercase;font-weight:600;white-space:nowrap}
.crit{border-left:2px solid var(--ink)}
.detail{color:var(--ink-2);font-size:13px;margin-top:3px;max-width:60ch}
.paths{margin-top:4px}
.paths code{font-size:11.5px;margin-right:6px;display:inline-block}

/* ---- notes / questions ---- */
.notes{border:1px solid var(--rule);border-left:3px solid var(--stop);
  background:var(--panel);padding:14px 18px;margin-bottom:24px}
.notes.calm{border-left-color:var(--muted)}
.notes h3{font-family:var(--cond);font-size:11px;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--muted);margin:0 0 8px;font-weight:600}
.notes ul{margin:0;padding-left:18px}
.notes li{margin:3px 0;font-size:14px;color:var(--ink-2)}
.ask{border:1px solid var(--accent);background:var(--panel);padding:16px 18px;
  margin-bottom:24px}
.ask h3{font-family:var(--cond);font-size:11px;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--accent);margin:0 0 9px;font-weight:600}
.ask ol{margin:0;padding-left:20px}
.ask li{margin:5px 0;max-width:66ch}
.ask .how{margin:12px 0 0;font-size:13.5px;color:var(--ink-2);
  border-top:1px solid var(--rule-soft);padding-top:10px}
blockquote{margin:0 0 22px;border-left:2px solid var(--rule);padding-left:16px;
  color:var(--ink-2);max-width:70ch}
blockquote .who{font-family:var(--cond);font-size:10.5px;letter-spacing:0.09em;
  text-transform:uppercase;color:var(--muted);display:block;margin-top:6px}

/* ---- review tab ---- */
.badge{background:var(--stop);color:#fff;border-radius:999px;font-size:10.5px;
  font-weight:700;padding:1px 6px;margin-left:2px;line-height:1.5}
h3.sec{font-family:var(--cond);font-size:11px;letter-spacing:0.11em;
  text-transform:uppercase;color:var(--muted);margin:34px 0 12px;
  padding-bottom:7px;border-bottom:1px solid var(--rule)}
ul.asks{margin:0;padding-left:17px}
ul.asks li{margin:2px 0}
ul.asks li.why{color:var(--stop)}
.timeline{list-style:none;margin:0;padding:0}
.ev{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--rule-soft)}
.ev:last-child{border-bottom:0}
.ev>.dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;margin-top:6px}
.ev>div{min-width:0;flex:1}
.evhead{font-size:14px;font-weight:500}
.evhead a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--rule)}
.evhead a:hover{color:var(--accent)}
.mutx{color:var(--muted);font-weight:400;font-size:12.5px}
.evnote{margin:5px 0 0;color:var(--ink-2);max-width:70ch}
.evfiles{margin:5px 0 0;font-size:12.5px;color:var(--muted)}
.evfiles code{margin-right:5px}

.tnote{font-size:13px;color:var(--muted);margin:0 0 12px;max-width:70ch}
td.t-stop{color:var(--stop);font-weight:500}
td.t-ok{color:var(--ok)}

.prose h2{font-size:19px;margin:26px 0 8px;font-weight:600}
.prose h3{font-size:16px;margin:20px 0 6px;font-weight:600}
.prose p{margin:0 0 11px;max-width:70ch}
.prose ul,.prose ol{max-width:70ch;padding-left:22px;margin:0 0 12px}
.prose li{margin:0 0 5px}
.prose ol{counter-reset:step;list-style:none;padding-left:30px}
.prose ol>li{counter-increment:step;position:relative}
.prose ol>li::before{content:counter(step);position:absolute;left:-30px;top:1px;width:20px;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums;font-weight:600}
.empty{color:var(--muted);font-size:14.5px;max-width:62ch}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--rule);
  color:var(--muted);font-size:12.5px}
@media (max-width:640px){
  .block-main h1{font-size:23px}
  .field{border-right:0;border-bottom:1px solid var(--rule-soft)}
  .metric{border-right:0;border-bottom:1px solid var(--rule-soft)}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def render_page(project: dict, phases: list[Phase]) -> str:
    o: list[str] = []
    a = o.append
    a(f"<title>{esc(project['title'])} Review</title>")
    a('<link rel="preconnect" href="https://fonts.googleapis.com">')
    a('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    a('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
      'family=IBM+Plex+Mono:wght@400;500&'
      'family=IBM+Plex+Sans+Condensed:wght@500;600&'
      'family=IBM+Plex+Sans:wght@400;500;600&display=swap">')
    a(f"<style>{CSS}</style>")
    a('<div class="wrap">')

    # ---- title block -----------------------------------------------------
    waiting = [p for p in phases if p.state in ("requested", "stale", "changes_requested")]
    a('<div class="block"><div class="block-main">')
    a(f"<h1>{esc(project['title'])}</h1>")
    if project.get("subtitle"):
        a(f"<p>{esc(project['subtitle'])}</p>")
    a("</div><div class='fields'>")
    slug, ref = project.get("repo"), project["branch"]
    tree = f"https://github.com/{slug}/tree/{ref}" if slug else None
    commit = f"https://github.com/{slug}/commit/{project['revision']}" if slug else None
    fields = [("Revision", project["revision"], commit),
              ("Branch", ref, tree),
              ("Generated", project["generated"], None),
              ("Phases", f"{len(phases)}", None),
              ("Awaiting you", str(len(waiting)) if waiting else "none",
               "#p-review" if waiting else None)]
    for k, v, href in fields:
        if href and href.startswith("#"):
            val = f'<a href="{esc(href)}" data-goto="review">{esc(v)} →</a>'
        elif href:
            val = (f'<a href="{esc(href)}" target="_blank" rel="noopener">'
                   f'{esc(v)} ↗</a>')
        else:
            val = esc(v)
        a(f'<div class="field"><span class="k">{esc(k)}</span>'
          f'<span class="v">{val}</span></div>')
    a("</div></div>")

    a('<div class="strip"><span class="k">Outstanding</span>')
    if waiting:
        names = ", ".join(p.title for p in waiting)
        a(f'<p><strong>{esc(names)}</strong> — '
          f'{"needs another look" if any(p.state == "stale" for p in waiting) else "waiting on your answer"}. '
          f'<a href="#p-review" data-goto="review">See what is being asked →</a></p>')
    else:
        a("<p>Nothing is waiting on you. Every phase below is signed off and "
          "still matches what you saw.</p>")
    a("</div>")

    # ---- tabs ------------------------------------------------------------
    a('<div class="tabs" role="tablist">')
    a(f'<button class="tab" role="tab" id="t-review" aria-controls="p-review" '
      f'aria-selected="false" data-tab="review">'
      f'<span class="dot b-{"stop" if waiting else "ok"}"></span>Review'
      + (f'<span class="badge">{len(waiting)}</span>' if waiting else "")
      + "</button>")
    for i, p in enumerate(phases):
        _lbl, tone = STATE_LABEL.get(p.state, STATE_LABEL["none"])
        a(f'<button class="tab" role="tab" id="t-{esc(p.id)}" '
          f'aria-controls="p-{esc(p.id)}" aria-selected="{"true" if i == 0 else "false"}" '
          f'data-tab="{esc(p.id)}"><span class="dot b-{tone}"></span>'
          f'{esc(p.title)}</button>')
    a("</div>")

    a('<section class="panel" role="tabpanel" id="p-review" '
      'aria-labelledby="t-review" hidden>')
    a(render_review_tab(phases))
    a("</section>")
    for i, p in enumerate(phases):
        a(f'<section class="panel" role="tabpanel" id="p-{esc(p.id)}" '
          f'aria-labelledby="t-{esc(p.id)}"{"" if i == 0 else " hidden"}>')
        a(render_phase(p))
        a("</section>")

    a(f'<footer>Generated by <code>review-artifact</code> from '
      f'{esc(project["repo"] or "the project repository")} at '
      f'<code>{esc(project["revision"])}</code>. Every figure and number here is '
      f'read from the file that owns it — nothing on this page is typed by hand. '
      f'Each phase is pinned to the commit it was reviewed at.</footer>')
    a("</div>")

    a("""<script>
const tabs=[...document.querySelectorAll('.tab')];
function show(id){
  tabs.forEach(t=>{const on=t.dataset.tab===id;
    t.setAttribute('aria-selected',on?'true':'false');
    document.getElementById('p-'+t.dataset.tab).hidden=!on;});
  try{localStorage.setItem('mh-phase',id)}catch(e){}
}
tabs.forEach(t=>t.addEventListener('click',()=>show(t.dataset.tab)));
// Anything with data-goto switches tab and scrolls, so the Review worklist
// can send you to the phase that raised the question.
document.addEventListener('click',e=>{
  const a=e.target.closest('[data-goto]'); if(!a)return;
  e.preventDefault(); show(a.dataset.goto);
  const el=document.getElementById('p-'+a.dataset.goto);
  if(el)el.scrollIntoView({behavior:'smooth',block:'start'});
});
tabs.forEach((t,i)=>t.addEventListener('keydown',e=>{
  const d=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;
  if(!d)return; e.preventDefault();
  const n=tabs[(i+d+tabs.length)%tabs.length]; n.focus(); show(n.dataset.tab);
}));
try{const s=localStorage.getItem('mh-phase');
  if(s&&tabs.some(t=>t.dataset.tab===s))show(s);}catch(e){}
</script>""")
    return "\n".join(o)


def render_review_tab(phases: list[Phase]) -> str:
    """What is being asked of you, and everything that has been asked before.

    Two jobs, and they are different. The top half is a worklist: the open
    questions, each linking to the phase that raises it, so "2 awaiting you" in
    the title block leads somewhere rather than just being a number. The bottom
    half is the project's memory — every round, what was asked, what came back,
    and what moved between rounds. That is the half nobody keeps and everybody
    later wishes they had.
    """
    o: list[str] = []
    a = o.append
    waiting = [p for p in phases
               if p.state in ("requested", "stale", "changes_requested")]

    a('<div class="phase-head"><div>')
    a('<span class="eyebrow">Across the project</span>')
    a("<h2>Review</h2></div>")
    a(f'<span class="pill t-{"stop" if waiting else "ok"}">'
      f'{len(waiting)} awaiting you</span></div>' if waiting
      else '<span class="pill t-ok">All clear</span></div>')

    if waiting:
        a('<div class="scroll"><table><thead><tr><th>Phase</th><th>State</th>'
          '<th>What we need decided</th><th>Since</th></tr></thead><tbody>')
        for p in waiting:
            label, tone = STATE_LABEL.get(p.state, STATE_LABEL["none"])
            r = p.review or {}
            qs = r.get("questions") or []
            body = "".join(f"<li>{esc(q)}</li>" for q in qs) or \
                "<li>Look it over and say whether it holds.</li>"
            if p.state == "stale":
                body += ("<li class=\"why\">Previously approved — "
                         + esc(", ".join(review_gate.drifted(r)))
                         + " changed since.</li>")
            a(f'<tr><td><a href="#p-{esc(p.id)}" data-goto="{esc(p.id)}">'
              f'{esc(p.title)}</a></td>'
              f'<td class="state t-{tone}">{esc(label)}</td>'
              f'<td><ul class="asks">{body}</ul></td>'
              f'<td class="num">{esc(r.get("requested", "—"))}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Nothing is waiting on you. Every phase is signed '
          "off and still matches what you saw.</p>")

    # ---- history ---------------------------------------------------------
    events = []
    for p in phases:
        for h in (p.review or {}).get("history") or []:
            events.append((h.get("on", ""), p, h))
    events.sort(key=lambda e: e[0], reverse=True)

    a('<h3 class="sec">History</h3>')
    if not events:
        a('<p class="empty">No review rounds recorded yet.</p>')
        return "\n".join(o)

    a('<ol class="timeline">')
    for on, p, h in events:
        action = h.get("action", "")
        tone = {"approved": "ok", "changes_requested": "stop",
                "requested": "wait"}.get(action, "idle")
        verb = {"approved": "approved", "changes_requested": "asked for changes",
                "requested": "sent for review"}.get(action, action)
        a(f'<li class="ev"><span class="dot b-{tone}"></span>')
        a(f'<div><div class="evhead"><a href="#p-{esc(p.id)}" '
          f'data-goto="{esc(p.id)}">{esc(p.title)}</a> '
          f'<span class="t-{tone}">{esc(verb)}</span>'
          + (f' <span class="mutx">by {esc(h["by"])}</span>' if h.get("by") else "")
          + f' <span class="mutx">{esc(on)}</span>'
          + (f' <code>{esc(h["commit"])}</code>' if h.get("commit") else "")
          + "</div>")
        if h.get("note"):
            a(f'<p class="evnote">{esc(h["note"])}</p>')
        if h.get("summary"):
            a(f'<p class="evnote">{esc(h["summary"])}</p>')
        moved = (h.get("changed") or []) + (h.get("added") or [])
        if moved:
            kind = "changed since the last round" if h.get("changed") else "added"
            a('<p class="evfiles">' + esc(kind) + ": "
              + "".join(f"<code>{esc(m)}</code>" for m in moved[:6]) + "</p>")
        if h.get("questions"):
            a("<ul class=\"asks\">"
              + "".join(f"<li>{esc(q)}</li>" for q in h["questions"]) + "</ul>")
        a("</div></li>")
    a("</ol>")
    return "\n".join(o)


def render_phase(p: Phase) -> str:
    o: list[str] = []
    a = o.append
    label, tone = STATE_LABEL.get(p.state, STATE_LABEL["none"])
    r = p.review or {}

    a('<div class="phase-head"><div>')
    if p.eyebrow:
        a(f'<span class="eyebrow">{esc(p.eyebrow)}</span>')
    a(f"<h2>{esc(r.get('title') or p.title)}</h2></div>")
    a(f'<span class="pill t-{tone}">{esc(label)}</span></div>')

    if r.get("summary"):
        a(f'<p class="summary">{esc(r["summary"].strip())}</p>')

    if p.metrics:
        a('<div class="metrics">')
        for n, l, s in p.metrics:
            a(f'<div class="metric"><div class="n">{esc(n)}</div>'
              f'<div class="l">{esc(l)}</div>'
              + (f'<div class="s">{esc(s)}</div>' if s else "") + "</div>")
        a("</div>")

    # The decision, or the ask — whichever this phase is at.
    if p.state == "approved":
        a(f'<blockquote>{esc(r.get("note") or "Approved.")}'
          f'<span class="who">{esc(r.get("reviewer") or "reviewer")} · '
          f'{esc(r.get("decided") or "")}</span></blockquote>')
    elif p.state == "stale":
        a('<div class="notes"><h3>Approved, then it moved</h3><ul>')
        for path in review_gate.drifted(r):
            a(f"<li><code>{esc(path)}</code> changed after sign-off</li>")
        a("</ul></div>")
        if r.get("note"):
            a(f'<blockquote>{esc(r["note"])}<span class="who">'
              f'{esc(r.get("reviewer") or "reviewer")} · on the previous version'
              f"</span></blockquote>")
    elif p.state == "changes_requested" and r.get("note"):
        a(f'<blockquote>{esc(r["note"])}<span class="who">changes requested · '
          f'{esc(r.get("decided") or "")}</span></blockquote>')

    if p.state in ("requested", "stale", "changes_requested") and r.get("questions"):
        a('<div class="ask"><h3>What we need decided</h3><ol>')
        for q in r["questions"]:
            a(f"<li>{esc(q)}</li>")
        a("</ol><p class=\"how\">Comment on this page — select the thing you are "
          "talking about and leave a note, or reply in the Claude session. Say "
          "which and <strong>why</strong>: the reason outlives the choice.</p></div>")

    for kind, payload in p.blocks:
        if kind == "figures":
            narrow = [f for f in payload if 0 < f.get("w", 0) <= 560]
            grid = len(payload) > 1 and len(narrow) == len(payload)
            if grid:
                a('<div class="figgrid">')
            for f in payload:
                a("<figure>")
                if f.get("svg"):
                    cap_w = f' style="max-width:{f["w"] + 34:.0f}px"' if f.get("w") else ""
                    mat = " mat" if f.get("mat") else ""
                    a(f'<div class="sheet{mat}"{cap_w}>{f["svg"]}</div>')
                elif f.get("uri"):
                    cap_w = f' style="max-width:{f["w"] + 34:.0f}px"' if f.get("w") else ""
                    mat = " mat" if f.get("mat") else ""
                    a(f'<div class="sheet{mat}"{cap_w}><img src="{f["uri"]}" '
                      f'alt="{esc(f.get("caption") or f["path"])}"></div>')
                elif f.get("warn"):
                    url = blob_url(f["path"])
                    link = (f' <a href="{esc(url)}" target="_blank" '
                            f'rel="noopener">Open on GitHub ↗</a>'
                            if url and f.get("link") else "")
                    a(f'<div class="notes"><h3>Not shown here</h3>'
                      f'<ul><li>{esc(f["warn"])}{link}</li></ul></div>')
                cap = f.get("caption") or _humanise(f["path"])
                a(f"<figcaption>{esc(cap)}")
                if f.get("editable"):
                    ed, dio = f["editable"], drawio_url(f["editable"])
                    bits = []
                    if dio:
                        bits.append(f'<a href="{esc(dio)}" target="_blank" '
                                    f'rel="noopener">Open in draw.io ↗</a>')
                    u = blob_url(ed)
                    if u:
                        bits.append(f'<a href="{esc(u)}" target="_blank" '
                                    f'rel="noopener">Get the .drawio ↗</a>')
                    if bits:
                        a(f'<span class="acts">{" · ".join(bits)}</span>')
                a("</figcaption></figure>")
            if grid:
                a("</div>")
        elif kind == "chunks":
            a(render_table(payload))
        elif kind == "prose":
            a(f'<div class="prose">{payload}</div>')
        elif kind == "csvtable":
            a(render_csv_table(payload))
        elif kind == "links":
            a(render_links(payload))

    if p.notes:
        a('<div class="notes calm"><h3>Worth a human\'s eye</h3><ul>')
        for n in p.notes[:14]:
            a(f"<li>{esc(n)}</li>")
        if len(p.notes) > 14:
            a(f"<li>… and {len(p.notes) - 14} more</li>")
        a("</ul></div>")

    if not p.blocks and not p.metrics:
        a('<p class="empty">This phase has been opened for review but has no '
          "artefacts on the page yet. Whatever is being reviewed lives in the "
          "repository — see the review packet.</p>")
    return "\n".join(o)


def render_csv_table(t: dict) -> str:
    o = [f'<h3 class="sec">{esc(t["title"])}</h3>']
    if t.get("note"):
        o.append(f'<p class="tnote">{esc(t["note"])}</p>')
    if t.get("estimated"):
        o.append(f'<div class="notes"><h3>{t["estimated"]} price(s) are not '
                 f'quoted</h3><ul><li>Rows marked in red carry an estimate, not '
                 f'a checked price. Treat the roll-up as indicative until they '
                 f'are quoted — a BOM cost built on guesses is the number that '
                 f'gets committed to.</li></ul></div>')
    o.append('<div class="scroll"><table><thead><tr>')
    for h in t["headers"]:
        o.append(f"<th>{esc(h)}</th>")
    o.append("</tr></thead><tbody>")
    for row in t["rows"]:
        cls = f' class="t-{row["tone"]}"' if row["tone"] else ""
        o.append("<tr>")
        for j, cell in enumerate(row["cells"]):
            num = ' class="num"' if re.fullmatch(
                r"[£$€]?[\d.,]+ ?%?", str(cell).strip()) else ""
            if j == t.get("basis_col") and row["tone"]:
                num = cls
            o.append(f"<td{num}>{esc(cell)}</td>")
        o.append("</tr>")
    o.append("</tbody></table></div>")
    if t.get("path"):
        url = blob_url(t["path"])
        o.append(f'<p class="tnote">Source: '
                 + (f'<a href="{esc(url)}" target="_blank" rel="noopener">'
                    f'<code>{esc(t["path"])}</code> ↗</a>' if url
                    else f'<code>{esc(t["path"])}</code>') + "</p>")
    return "\n".join(o)


def render_links(payload: dict) -> str:
    """The checklist: what a run needs, whether it exists, and where it is.

    This is the whole of the manufacturing tab and the tail of most others.
    The point is not to show the documents — a fabrication drawing rendered
    small on a review page tells nobody anything they can act on — it is to
    show at a glance that the set is complete, and to be one click from any of
    it. So the state column carries the weight, and a missing row stays in
    place saying it is missing rather than quietly not being there.
    """
    rows = payload.get("rows") or []
    if not rows:
        return ""
    missing = sum(1 for r in rows if r["missing"])
    o = [f'<h3 class="sec">{esc(payload.get("title") or "Documents a run needs")}</h3>']
    if payload.get("note"):
        o.append(f'<p class="lead">{esc(payload["note"])}</p>')
    o.append(f'<p class="tally">{len(rows) - missing} of {len(rows)} present'
             + (f' · <span class="t-stop">{missing} still to produce</span>'
                if missing else " · complete") + "</p>")
    o.append('<div class="scroll"><table><thead><tr><th>Document</th>'
             '<th>State</th><th>What it is for</th></tr></thead><tbody>')

    group = object()                       # never equal to a real group name
    for lk in rows:
        if lk.get("group", "") != group:
            group = lk.get("group", "")
            if group:
                o.append(f'<tr class="grp"><td colspan="3">{esc(group)}</td></tr>')
        if lk["missing"]:
            state, tone = "Not produced", "stop"
            name = esc(lk["label"])
        else:
            state, tone = "Ready", "ok"
            name = (f'<a href="{esc(lk["url"])}" target="_blank" rel="noopener">'
                    f'{esc(lk["label"])} \u2197</a>' if lk["url"]
                    else esc(lk["label"]))
            if lk.get("drawio"):
                name += (f' <a class="alt" href="{esc(lk["drawio"])}" '
                         f'target="_blank" rel="noopener">open in draw.io '
                         f'\u2197</a>')
        o.append(f'<tr><td>{name}<div class="paths"><code>{esc(lk["path"])}</code>'
                 f'</div></td><td class="state t-{tone}">{state}</td>'
                 f'<td>{esc(lk["why"])}</td></tr>')
    o.append("</tbody></table></div>")
    return "\n".join(o)


def render_table(t: dict) -> str:
    """A data table. `detail_col` says which column carries the prose, if any.

    It used to be hardcoded to column 1, which is the title on the plan and
    requirements tables and the *voltage* on the power table — so a rail's
    notes were rendered under a number, took the column's whole width and
    pushed the rest of the row out of line. A table of numbers should be a
    table of numbers.
    """
    detail_col = t.get("detail_col")
    # State sits second, right after the identifier: it is the column a reader
    # scans first, and it was stranded at the far right past five numbers.
    o = ['<div class="scroll"><table><thead><tr>',
         f'<th>{esc(t["headers"][0])}</th><th>State</th>']
    for h in t["headers"][1:]:
        o.append(f"<th>{esc(h)}</th>")
    o.append("</tr></thead><tbody>")
    for row in t["rows"]:
        cls = ' class="crit"' if row.get("crit") else ""
        o.append(f"<tr{cls}>")
        o.append(f'<td>{esc(row["cells"][0])}</td>'
                 f'<td class="state t-{row.get("tone", "idle")}">'
                 f'{esc(row.get("state", ""))}</td>')
        for j, cell in enumerate(row["cells"][1:], start=1):
            num = ' class="num"' if re.fullmatch(
                r"[\d.,+\-—%]+ ?\w{0,3}", str(cell)) else ""
            o.append(f"<td{num}>{esc(cell)}")
            if j == detail_col:
                if row.get("detail"):
                    o.append(f'<div class="detail">{esc(row["detail"])}</div>')
                if row.get("outputs"):
                    o.append('<div class="paths">'
                             + "".join(f"<code>{esc(p)}</code>"
                                       for p in row["outputs"][:5]) + "</div>")
            o.append("</td>")
        o.append("</tr>")
    o.append("</tbody></table></div>")
    return "\n".join(o)


# ---------------------------------------------------------------------------
# The design-stage phases a hardware project grows, in the order they happen.
# `--init` writes all of them: the ones with artefacts already on disk wired up,
# the rest present but commented, because a phase nobody remembers to add is a
# phase that never appears on the page. Each carries the paths the toolbox
# actually writes, so the common case is uncommenting three lines.
INIT_STAGES = [
    ("cad", "CAD", "Stage 5 · mechanical", "architecture",
     ["docs/design/cad/enclosure-render.png",
      "docs/design/cad/enclosure-section.svg"], []),
    ("schematic", "Schematic", "Stage 5 · electrical", "cad",
     ["docs/design/schematic/sheet-1.svg"], ["docs/design/adr-0001.md"]),
    ("layout", "PCB layout", "Stage 5 · electrical", "schematic",
     ["docs/design/pcb-top.png", "docs/design/stackup.svg"], []),
    ("simulation", "Simulation", "Stage 6", "layout",
     ["docs/design/sim-results.svg"], ["docs/design/sim-results.md"]),
    ("mfg", "Manufacturing", "Stage 7", "simulation", [], []),
]

MFG_CHECKLIST = [
    ("Fabrication", "docs/design/pcb-fab.zip", "Gerbers and drill files",
     "RS-274X plus the drill schedule"),
    ("Fabrication", "docs/design/mfg/fab-drawing.svg", "Fabrication drawing",
     "Outline, hole schedule and tolerances"),
    ("Fabrication", "docs/design/stackup.svg", "Stackup drawing",
     "What the fab quotes against"),
    ("Fabrication", "docs/design/mfg/fab-notes.md", "Fabrication notes",
     "Material, finish, class, panelisation"),
    ("Assembly", "docs/design/mfg/assembly-drawing.svg", "Assembly drawing",
     "Placement, orientation and polarity"),
    ("Assembly", "docs/design/pcb-pos.csv", "Pick and place",
     "Centroid file"),
    ("Assembly", "docs/design/bom-summary.csv", "BOM",
     "Purchasing and the assembly house"),
    ("Assembly", "docs/design/mfg/assembly-process.md",
     "Assembly and test process", "The traveller, then the test sequence"),
    ("Commercial", "docs/design/mfg/quotes.csv", "Quotes",
     "Supplier, quantity, tooling, lead time and the date each was given"),
    ("Commercial", "docs/design/mfg/supplier-decision.md",
     "Supplier decision", "Which quote was taken and why"),
]


def init_config(root: str, out: str) -> int:
    """Write a starter `docs/review/artifact.yaml` shaped by what is here.

    Without this file only the four standard milestones appear, so every
    design stage a project actually does — the schematic, the layout, the
    enclosure, the simulation campaign, the release — is invisible on the
    review page. Nobody writes that config from a blank file, so generate it:
    phases whose artefacts exist are live, the rest are commented out with the
    paths the toolbox writes, and turning one on is uncommenting three lines.
    """
    if os.path.exists(out):
        print(f"{os.path.relpath(out, root)} already exists — not overwriting.")
        print("Delete it first if you want a fresh one.")
        return 1

    plan = read_yaml(os.path.join(root, "plan.yaml")) or {}
    title = plan.get("project") or os.path.basename(root).replace("-", " ").title()

    o = [
        "# Which phases the review page shows, and what goes in each.",
        "#",
        "# Vision, plan, requirements and architecture are built automatically",
        "# from the repo and need nothing here. Everything below is a design",
        "# stage: it appears on the page only if it is listed.",
        "#",
        "# Regenerate the page with `review-artifact`, and check it with",
        "# `review-artifact --check` before you publish it.",
        f"title: {title}",
        "subtitle: >-",
        "  One or two lines on what this is and who it is for.",
        "",
        "phases:",
    ]

    for pid, ptitle, eyebrow, after, images, docs in INIT_STAGES:
        live = [i for i in images if os.path.exists(os.path.join(root, i))]
        have = bool(live) or (pid == "mfg")
        c = "" if have else "# "
        o.append(f"{c}  - id: {pid}")
        o.append(f"{c}    title: {ptitle}")
        o.append(f"{c}    eyebrow: {eyebrow}")
        o.append(f"{c}    after: {after}")
        if pid == "mfg":
            o.append(f"{c}    links_title: Release checklist")
            o.append(f"{c}    links_note: >-")
            o.append(f"{c}      Everything a fab, an assembler and a purchaser "
                     f"need in order to")
            o.append(f"{c}      quote and build. Rows still to produce are the "
                     f"answer to \"can we")
            o.append(f"{c}      release?\" — leave them listed.")
            o.append(f"{c}    links:")
            for group, path, label, why in MFG_CHECKLIST:
                o.append(f"{c}      - {{group: {group}, path: {path},")
                o.append(f"{c}         label: {label}, why: \"{why}\"}}")
        else:
            o.append(f"{c}    images:")
            for i in (live or images):
                o.append(f"{c}      - {i}")
            o.append(f"{c}    captions:")
            for i in (live or images):
                o.append(f"{c}      {i}: >-")
                o.append(f"{c}        What this shows, and the thing you want "
                         f"looked at.")
            if docs:
                o.append(f"{c}    docs: [{', '.join(docs)}]")
        o.append("")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as fh:
        fh.write("\n".join(o).rstrip() + "\n")

    rel = os.path.relpath(out, root)
    live = [st[0] for st in INIT_STAGES
            if st[0] == "mfg" or any(os.path.exists(os.path.join(root, i))
                                     for i in st[4])]
    print(f"wrote {rel}")
    print(f"  live now:   {', '.join(live) or 'none'}")
    print(f"  commented:  {', '.join(st[0] for st in INIT_STAGES if st[0] not in live)}")
    print()
    print("Uncomment a phase once its artefacts exist, then run "
          "`review-artifact`.")
    return 0


def record_url(root: str, url: str) -> int:
    """Remember where this project's review page lives."""
    if not re.match(r"https://claude\.ai/[\w/-]*artifact/[0-9a-f-]{16,}",
                    url.strip()):
        print(f"That does not look like an artifact URL: {url}")
        print("Expected something like "
              "https://claude.ai/code/artifact/<id>")
        return 1
    path = os.path.join(root, review_gate.LEDGER)
    data = review_gate.load(path)
    was = data.get("artifact_url")
    data["artifact_url"] = url.strip()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    review_gate.save(data, path)
    print(f"{'replaced' if was else 'recorded'} in {review_gate.LEDGER}:")
    if was:
        print(f"  was  {was}")
    print(f"  now  {url.strip()}")
    print("\nCommit it — the next session reads this to republish in place.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="project root")
    ap.add_argument("--out", default="docs/review/artifact.html")
    ap.add_argument("--title", help="overrides plan.yaml / artifact.yaml")
    ap.add_argument("--check", action="store_true",
                    help="report artefacts that cannot be shown; write nothing. "
                         "Exit 1 if any. Run this before publishing.")
    ap.add_argument("--url", metavar="URL",
                    help="record the published artifact's URL in the ledger, "
                         "so every later session republishes to that page "
                         "rather than creating a second one. Then stop.")
    ap.add_argument("--init", action="store_true",
                    help="write a starter docs/review/artifact.yaml shaped by "
                         "what this repo already contains, then stop. Run once "
                         "per project.")
    args = ap.parse_args()

    if args.init:
        return init_config(os.path.abspath(args.project),
                           os.path.join(os.path.abspath(args.project),
                                        "docs/review/artifact.yaml"))

    if args.url:
        return record_url(os.path.abspath(args.project), args.url)

    global _inlined
    _inlined = 0                    # --check and the write are separate runs

    root = os.path.abspath(args.project)
    cfg = read_yaml(os.path.join(root, "docs/review/artifact.yaml")) or {}
    plan = read_yaml(os.path.join(root, "plan.yaml")) or {}

    cwd = os.getcwd()
    os.chdir(root)
    try:
        revision = review_gate._git("rev-parse", "--short", "HEAD") or "uncommitted"
        branch = review_gate.head_ref()
        repo = review_gate.repo_slug()
    finally:
        os.chdir(cwd)

    import datetime
    REPO["slug"], REPO["ref"] = repo, branch
    project = {
        "title": args.title or cfg.get("title") or plan.get("project") or "Project",
        "subtitle": cfg.get("subtitle", ""),
        "revision": revision, "branch": branch, "repo": repo,
        "generated": datetime.date.today().isoformat(),
    }

    phases = collect(root, cfg)
    if not phases:
        sys.stderr.write("Nothing to review yet: no vision, plan, requirements "
                         "or block diagram found, and no reviews in the ledger.\n")
        return 1

    # Preflight: everything that was asked for and could not be shown. An
    # agent should run this before publishing, because the page it is about to
    # put in front of a human is the last place to discover a failed export.
    problems = [(p.id, f["warn"]) for p in phases
                for kind, payload in p.blocks if kind == "figures"
                for f in payload if f.get("warn")]

    if args.check:
        if problems:
            print(f"{len(problems)} artefact(s) cannot be shown:\n")
            for pid, w in problems:
                print(f"  {pid:<14} {w}")
            return 1
        print(f"review page is clear ({len(phases)} phases, "
              f"every artefact embeddable)")
        return 0

    out = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as fh:
        fh.write(render_page(project, phases))

    size = os.path.getsize(out)
    print(f"wrote {os.path.relpath(out, cwd)}  ({size // 1024} kB, "
          f"{len(phases)} phase(s))")
    for p in phases:
        label, _ = STATE_LABEL.get(p.state, STATE_LABEL["none"])
        note = ""
        n = sum(1 for kind, payload in p.blocks if kind == "figures"
                for f in payload if f.get("warn"))
        if n:
            note = f"   ({n} artefact(s) not shown)"
        print(f"  {p.id:<15} {label}{note}")

    if problems:
        print(f"\n  {len(problems)} artefact(s) could not be embedded. Each is "
              f"reported on the page\n  rather than silently dropped, but fix "
              f"the export if you can:")
        for pid, w in problems[:8]:
            print(f"    {pid:<12} {w}")

    # The artifact cap is 16 MB and a page of real board renders reaches it
    # far sooner than a page of diagrams does.
    if size > 12 * 1024 * 1024:
        print(f"\n  TOO BIG: {size // 1024 // 1024} MB against a 16 MB cap. "
              f"Downscale the rasters before publishing.")
        return 1
    if size > 6 * 1024 * 1024:
        print(f"\n  WARNING: {size // 1024 // 1024} MB of a 16 MB cap. "
              f"Downscale rasters before adding more phases.")
    # One project, one page. A session that publishes without the existing URL
    # creates a *second* artifact, and now there are two review pages with
    # different content and the human is reading whichever one they happened to
    # bookmark. So the URL lives in the ledger, and this says which case it is.
    url = (read_yaml(os.path.join(root, review_gate.LEDGER)) or {}).get("artifact_url")
    print()
    if url:
        print("Publish with the Artifact tool, passing this as `url` so it "
              "updates in place:")
        print(f"  {url}")
    else:
        print("Publish it with the Artifact tool, then record the URL so the "
              "next session updates the same page instead of making a second "
              "one:")
        print("  review-artifact --url <the artifact URL>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
