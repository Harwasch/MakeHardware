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

Usage:
    scripts/vision_board.py concepts/concept_a.py [concepts/concept_b.py ...] \
        --out build/vision

Each concept file is a plain Python module that defines:
    PART   : a build123d Part / Compound          (required)
    TITLE  : str                                  (optional)
    NOTES  : str                                  (optional)

Writes <out>/<stem>/{iso.svg,view-*.png} plus <out>/manifest.json, which is
what you feed into the vision-board Artifact.
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
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("concepts", nargs="+", help="python files each defining PART")
    ap.add_argument("--out", default="build/vision")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
