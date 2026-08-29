#!/usr/bin/env python3
"""Render build123d concepts into images a human can actually judge.

The point of the vision stage is that people are far better at reacting to a
picture than to a paragraph. This turns a parametric build123d model into the
two things worth looking at:

  * shaded three-quarter views      — "does that look like the thing I meant?"
  * an isometric line drawing       — "how big is it, where do the seams fall?"

Both come from real geometry, so unlike an image model the pictures cannot
show something unbuildable, and every one of them is attached to numbers.
When the human says "too tall", you change a parameter and re-render.

The renders default to `docs/design/vision/`, not to `build/`, and a vision
**document** is written beside them. That is deliberate: the human reviewing
this is usually looking at github.com while the agent works in a cloud VM, so
an image under `build/` is an image nobody will ever see. `docs/design/vision.md`
renders inline on GitHub with every concept, its numbers and the open
questions, and it is the artefact the vision review signs off.

Usage:
    scripts/vision_board.py concepts/concept_a.py [concepts/concept_b.py ...]

    scripts/vision_board.py concepts/*.py \
        --out docs/design/vision --doc docs/design/vision.md \
        --question "Which of these, and why?"

Each concept file is a plain Python module that defines:
    PART      : a build123d Part / Compound          (required)
    TITLE     : str                                  (optional)
    NOTES     : str                                  (optional)
    MATERIAL  : str                                  (optional)
    RATIONALE : str  — what this concept is betting on (optional)

Writes <out>/<stem>/{iso.svg,view-*.png}, <out>/manifest.json and the vision
document.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from build123d import ExportSVG, LineType

# Camera angles worth showing. A hero three-quarter, a front, and a top.
VIEWS = {
    "hero":  dict(elev=24,  azim=-125),
    "front": dict(elev=6,   azim=-90),
    "top":   dict(elev=78,  azim=-90),
}

MATERIALS = {
    "graphite": (0.38, 0.40, 0.45),
    "steel":    (0.62, 0.65, 0.70),
    "cobalt":   (0.36, 0.55, 0.85),
    "sand":     (0.80, 0.74, 0.62),
}


def _subdivide(tris: np.ndarray, max_edge: float, max_passes: int = 6) -> np.ndarray:
    """Split triangles until no edge exceeds max_edge.

    Matplotlib depth-sorts each polygon by a single representative depth, so a
    few big triangles across a flat face get ordered wrongly against the walls
    of a pocket and the seams show up as diagonal creases. Uniform small
    triangles make that failure invisible. OCCT will not do this for us: a
    planar face triangulates to a handful of triangles no matter the
    tolerance, because tolerance bounds deviation from curvature.
    """
    for _ in range(max_passes):
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        longest = np.maximum.reduce([
            np.linalg.norm(b - a, axis=1),
            np.linalg.norm(c - b, axis=1),
            np.linalg.norm(a - c, axis=1),
        ])
        big = longest > max_edge
        if not big.any():
            break
        keep, split = tris[~big], tris[big]
        a, b, c = split[:, 0], split[:, 1], split[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        tris = np.concatenate([
            keep,
            np.stack([a, ab, ca], axis=1),
            np.stack([ab, b, bc], axis=1),
            np.stack([ca, bc, c], axis=1),
            np.stack([ab, bc, ca], axis=1),
        ])
    return tris


def _tessellate(part, tolerance: float = 0.1):
    verts, faces = part.tessellate(tolerance=tolerance)
    V = np.array([(v.X, v.Y, v.Z) for v in verts], dtype=float)
    tris = V[np.array(faces)]
    extent = np.ptp(V, axis=0).max()
    return _subdivide(tris, max_edge=extent / 22.0)


def shaded_png(part, path: str, elev: float, azim: float,
               material: str = "cobalt", dpi: int = 170) -> str:
    """Flat-shaded render from a tessellation. Two-sided so cavities read."""
    tris = _tessellate(part)

    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9

    # Key light plus a weaker fill from the opposite side. One-sided (clipped,
    # not abs) lighting is what makes a pocket read AS a pocket: the cavity
    # walls fall away from the key and go visibly darker than the top face.
    # The fill and the ambient floor stop them crushing to black.
    def _lit(vec):
        v = np.array(vec, dtype=float)
        return np.clip(n @ (v / np.linalg.norm(v)), 0, 1)

    shade = 0.13 + 0.70 * _lit([0.4, -0.6, 0.7]) + 0.22 * _lit([-0.5, 0.35, 0.2])
    shade = np.clip(shade, 0, 1)

    base = np.array(MATERIALS.get(material, MATERIALS["cobalt"]))
    colors = np.clip(shade[:, None] * base[None, :], 0, 1)

    fig = plt.figure(figsize=(7, 5), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    # Give every triangle an edge in its own face colour and turn antialiasing
    # off: with edgecolors="none" the AA gaps between neighbours show up as a
    # fine mesh texture over the whole surface.
    ax.add_collection3d(Poly3DCollection(
        tris, facecolors=colors, edgecolors=colors,
        linewidths=0.35, antialiased=False))

    centre = tris.reshape(-1, 3).mean(axis=0)
    radius = np.ptp(tris.reshape(-1, 3), axis=0).max() / 2 * 1.05
    ax.set_xlim(centre[0] - radius, centre[0] + radius)
    ax.set_ylim(centre[1] - radius, centre[1] + radius)
    ax.set_zlim(centre[2] - radius, centre[2] + radius)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.savefig(path, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return path


def iso_svg(part, path: str, scale: float = 3.0) -> str:
    """Isometric line drawing with hidden edges dashed."""
    visible, hidden = part.project_to_viewport(
        viewport_origin=(220, -180, 160),
        viewport_up=(0, 0, 1),
        look_at=(0, 0, 0),
    )
    exporter = ExportSVG(scale=scale, margin=6)
    exporter.add_layer("hidden", line_color=(160, 160, 160),
                       line_type=LineType.ISO_DOT, line_weight=0.25)
    exporter.add_layer("visible", line_color=(20, 20, 20), line_weight=0.5)
    exporter.add_shape(hidden, layer="hidden")
    exporter.add_shape(visible, layer="visible")
    exporter.write(path)
    return path


def measure(part) -> dict:
    bb = part.bounding_box()
    size = bb.size
    return {
        "bbox_mm": [round(size.X, 2), round(size.Y, 2), round(size.Z, 2)],
        "volume_mm3": round(part.volume, 1),
        # Handy sanity number during the vision stage: mass at a plausible
        # average density for a populated plastic-and-battery assembly.
        "approx_mass_g_at_1p4": round(part.volume * 1.4e-3, 1),
    }


def load_concept(path: str):
    spec = importlib.util.spec_from_file_location("concept", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "PART"):
        raise SystemExit(f"{path}: module defines no PART")
    return module


def render_concept(path: str, outdir: str, material: str = "cobalt") -> dict:
    module = load_concept(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    target = os.path.join(outdir, stem)
    os.makedirs(target, exist_ok=True)

    part = module.PART
    entry = {
        "id": stem,
        "title": getattr(module, "TITLE", stem.replace("_", " ").title()),
        "notes": getattr(module, "NOTES", ""),
        "rationale": getattr(module, "RATIONALE", ""),
        "material": getattr(module, "MATERIAL", material),
        "source": path,
        "metrics": measure(part),
        "images": {},
    }
    for name, angle in VIEWS.items():
        out = os.path.join(target, f"view-{name}.png")
        shaded_png(part, out, material=getattr(module, "MATERIAL", material), **angle)
        entry["images"][name] = os.path.relpath(out, outdir)
    out = os.path.join(target, "iso.svg")
    iso_svg(part, out)
    entry["images"]["iso"] = os.path.relpath(out, outdir)

    # Styling imagery, if hw-imagegen has already produced any. It is picked
    # up by filename rather than passed in, so re-running the board after a
    # styling pass folds the new images into the document automatically.
    entry["styling"] = sorted(
        os.path.relpath(os.path.join(target, f), outdir)
        for f in os.listdir(target)
        if f.startswith("style-") and f.lower().endswith((".png", ".jpg", ".webp")))
    return entry


# ---------------------------------------------------------------------------
# The vision document
#
# The reason this exists rather than only an Artifact: the human is reviewing
# from github.com, usually on a different machine from the one the agent is
# working on. A render that is not committed to the repository, in a file that
# GitHub renders, is a render nobody sees — and a vision stage reported as
# complete on renders nobody saw is exactly the failure this document is here
# to stop.
# ---------------------------------------------------------------------------
VISION_DOC = "docs/design/vision.md"


def render_doc(manifest: dict, outdir: str, doc_path: str,
               project: str | None = None,
               description: str | None = None,
               questions: list[str] | None = None) -> str:
    concepts = manifest["concepts"]
    base = os.path.dirname(doc_path) or "."

    def rel(img: str) -> str:
        return os.path.relpath(os.path.join(outdir, img), base)

    o = [f'# Vision — {project or "this product"}', "",
         "What we think you asked for, drawn from real geometry. Every image "
         "below comes from a parametric model, so nothing here is a shape that "
         "cannot be built, and every number is measured off the model rather "
         "than estimated.", ""]
    if description:
        o += [description.strip(), ""]

    if len(concepts) > 1:
        o += ["## The choice", "",
              "| | " + " | ".join(f'**{c["title"]}**' for c in concepts) + " |",
              "|---|" + "---|" * len(concepts) + "",
              "| Envelope (mm) | " + " | ".join(
                  " × ".join(str(v) for v in c["metrics"]["bbox_mm"])
                  for c in concepts) + " |",
              "| Volume (mm³) | " + " | ".join(
                  f'{c["metrics"]["volume_mm3"]:,.0f}' for c in concepts) + " |",
              "| Approx. mass (g) | " + " | ".join(
                  f'{c["metrics"]["approx_mass_g_at_1p4"]:,.0f}' for c in concepts) + " |",
              ""]

    for c in concepts:
        m = c["metrics"]
        o += [f'## {c["title"]}', ""]
        if c.get("notes"):
            o += [c["notes"].strip(), ""]
        if c.get("rationale"):
            o += [f'**What this one bets on:** {c["rationale"].strip()}', ""]
        o += [f'**{" × ".join(str(v) for v in m["bbox_mm"])} mm** · '
              f'{m["volume_mm3"]:,.0f} mm³ · '
              f'~{m["approx_mass_g_at_1p4"]:,.0f} g at 1.4 g/cm³ · '
              f'model: `{c["source"]}`', ""]

        if "hero" in c["images"]:
            o += [f'![{c["title"]} — three-quarter view]({rel(c["images"]["hero"])})', ""]
        pair = [k for k in ("front", "top") if k in c["images"]]
        if pair:
            o += ["| " + " | ".join(k.title() for k in pair) + " |",
                  "|" + "---|" * len(pair),
                  "| " + " | ".join(f'![{k}]({rel(c["images"][k])})' for k in pair) + " |",
                  ""]
        if "iso" in c["images"]:
            o += ["<details><summary>Dimensioned isometric line drawing</summary>", "",
                  f'![{c["title"]} — isometric]({rel(c["images"]["iso"])})', "",
                  "</details>", ""]
        if c.get("styling"):
            o += ["### Styling proposals", "",
                  "*Generated imagery — styling only. These carry no dimensions; "
                  "the numbers above and the line drawing are the geometry.*", ""]
            for img in c["styling"]:
                o += [f'![styling proposal — generated, not dimensioned]({rel(img)})', ""]

    o += ["## What we need from you", ""]
    for i, q in enumerate(questions or [
            "Which concept, and what made you pick it? The reason matters more "
            "than the choice.",
            "Is anything in the envelope wrong — too big, too small, wrong "
            "proportions?",
            "What is missing that you assumed we knew?"], 1):
        o += [f"{i}. {q}"]
    o += ["",
          "Whatever you agree to here becomes the `VIS-` entries in "
          "`requirements/00-vision.sdoc`, in your words, and everything "
          "downstream is built on it.", "",
          "---", "",
          "<sub>Generated by `vision-board` from the models in `concepts/`. "
          "Change a parameter and re-run; do not edit this file.</sub>", ""]

    os.makedirs(base, exist_ok=True)
    with open(doc_path, "w") as fh:
        fh.write("\n".join(o))
    return doc_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("concepts", nargs="+", help="python files each defining PART")
    ap.add_argument("--out", default="docs/design/vision",
                    help="where the renders go — under docs/ so GitHub shows them")
    ap.add_argument("--doc", default=VISION_DOC,
                    help="the vision document; --doc '' to skip")
    ap.add_argument("--project", help="product name for the document title")
    ap.add_argument("--description",
                    help="the vision in prose, in the human's words")
    ap.add_argument("--question", action="append",
                    help="a question to put to the human; repeatable")
    ap.add_argument("--material", default="cobalt", choices=sorted(MATERIALS))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    manifest = {"concepts": []}
    for path in args.concepts:
        entry = render_concept(path, args.out, args.material)
        manifest["concepts"].append(entry)
        m = entry["metrics"]
        print(f"{entry['id']:<18} {m['bbox_mm']} mm   "
              f"{m['volume_mm3']:>10} mm3   ~{m['approx_mass_g_at_1p4']} g")

    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\n{len(manifest['concepts'])} concept(s) -> {args.out}/manifest.json")

    if args.doc:
        render_doc(manifest, args.out, args.doc, args.project,
                   args.description, args.question)
        print(f"wrote {args.doc}")
        print("\nCommit and push the document and the renders, then open the "
              "review:\n"
              f"  review-gate open vision --artifact {args.doc} "
              f"--artifact {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
