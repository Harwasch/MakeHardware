#!/usr/bin/env python3
"""Build the parts of the example project that need tools this container lacks.

The plan chart, the block diagram and the power budget are produced by the real
MakeHardware tools. This fills in the two that cannot be: the vision renders
(build123d is not installed here) and the requirements export (strictdoc is
not). Both are written in exactly the shape the real tools emit, so the review
artifact generator reads the fixture and a real project identically.

    python3 build-fixture.py
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "plugins", "makehardware", "scripts"))

# The MakeHardware palette, so fixture drawings sit flush beside real output.
INK, INK2, MUTED, RULE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
FONT = ("ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")


def elevation(w_mm: float, h_mm: float, d_mm: float, title: str,
              features: list[tuple[str, float, float, float, float]]) -> str:
    """A dimensioned two-view outline, the way a vision render reads.

    features are (kind, x, y, w, h) in mm on the front face, where kind is
    'screen', 'button' or 'port'.
    """
    scale = 2.2
    pad, gap = 54, 46
    fw, fh = w_mm * scale, h_mm * scale
    sw = d_mm * scale
    width = pad * 2 + fw + gap + sw + 40
    height = pad * 2 + fh + 34

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
         f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
         f'font-family="{FONT}" role="img" aria-label="{title}: '
         f'{w_mm} by {h_mm} by {d_mm} millimetres">']
    o.append("<style>"
             f".o{{fill:none;stroke:{INK};stroke-width:1.6}}"
             f".f{{fill:none;stroke:{INK2};stroke-width:1}}"
             f".d{{stroke:{MUTED};stroke-width:0.7}}"
             f".t{{font-size:10px;fill:{MUTED}}}"
             f".lbl{{font-size:10.5px;fill:{INK2};font-weight:600;"
             "letter-spacing:0.06em}"
             "</style>")

    x0, y0 = pad, pad
    o.append(f'<rect x="{x0}" y="{y0}" width="{fw:.1f}" height="{fh:.1f}" '
             f'rx="{6 * scale:.1f}" class="o"/>')
    for kind, fx, fy, fwm, fhm in features:
        rx = {"screen": 2, "button": 8, "port": 3}.get(kind, 2)
        o.append(f'<rect x="{x0 + fx * scale:.1f}" y="{y0 + fy * scale:.1f}" '
                 f'width="{fwm * scale:.1f}" height="{fhm * scale:.1f}" '
                 f'rx="{rx}" class="f"/>')

    # side elevation
    sx = x0 + fw + gap
    o.append(f'<rect x="{sx:.1f}" y="{y0}" width="{sw:.1f}" height="{fh:.1f}" '
             f'rx="{6 * scale:.1f}" class="o"/>')

    # dimension lines: width under the front view, height left of it
    dy = y0 + fh + 20
    o.append(f'<line x1="{x0}" y1="{dy}" x2="{x0 + fw:.1f}" y2="{dy}" class="d"/>'
             f'<line x1="{x0}" y1="{dy - 4}" x2="{x0}" y2="{dy + 4}" class="d"/>'
             f'<line x1="{x0 + fw:.1f}" y1="{dy - 4}" x2="{x0 + fw:.1f}" '
             f'y2="{dy + 4}" class="d"/>')
    o.append(f'<text x="{x0 + fw / 2:.1f}" y="{dy + 15}" class="t" '
             f'text-anchor="middle">{w_mm:g} mm</text>')

    dx = x0 - 16
    o.append(f'<line x1="{dx}" y1="{y0}" x2="{dx}" y2="{y0 + fh:.1f}" class="d"/>'
             f'<line x1="{dx - 4}" y1="{y0}" x2="{dx + 4}" y2="{y0}" class="d"/>'
             f'<line x1="{dx - 4}" y1="{y0 + fh:.1f}" x2="{dx + 4}" '
             f'y2="{y0 + fh:.1f}" class="d"/>')
    o.append(f'<text x="{dx - 8}" y="{y0 + fh / 2:.1f}" class="t" '
             f'text-anchor="middle" transform="rotate(-90 {dx - 8} '
             f'{y0 + fh / 2:.1f})">{h_mm:g} mm</text>')

    sdy = y0 + fh + 20
    o.append(f'<line x1="{sx:.1f}" y1="{sdy}" x2="{sx + sw:.1f}" y2="{sdy}" class="d"/>')
    o.append(f'<text x="{sx + sw / 2:.1f}" y="{sdy + 15}" class="t" '
             f'text-anchor="middle">{d_mm:g}</text>')

    o.append(f'<text x="{x0}" y="{y0 - 16}" class="lbl">FRONT</text>')
    o.append(f'<text x="{sx:.1f}" y="{y0 - 16}" class="lbl">SIDE</text>')
    o.append("</svg>")
    return "\n".join(o)


CONCEPTS = [
    dict(stem="concept_a", title="Wand",
         w=38, h=164, d=22, volume=72840, mass=102,
         notes="One-handed. Probe on a 300 mm flex lead so the body never "
               "enters the cold zone. Two-digit display, one button.",
         rationale="That the freezer walk is the whole job, so the display can "
                   "be small and the body has to survive a glove.",
         features=[("screen", 6, 12, 26, 18), ("button", 14, 40, 10, 10),
                   ("port", 14, 152, 10, 5)]),
    dict(stem="concept_b", title="Bench instrument",
         w=92, h=118, d=34, volume=214600, mass=300,
         notes="Sits on a shelf in the plant room and gets picked up. Four-digit "
               "display with a trend strip, dock contacts on the base.",
         rationale="That it lives in one place and is read at arm's length, so "
                   "it can be wider and carry a bigger cell.",
         features=[("screen", 10, 14, 72, 34), ("button", 12, 60, 14, 14),
                   ("button", 34, 60, 14, 14), ("port", 40, 110, 12, 5)]),
]


def build_vision() -> None:
    out = os.path.join(HERE, "docs", "design", "vision")
    os.makedirs(out, exist_ok=True)
    for c in CONCEPTS:
        d = os.path.join(out, c["stem"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "elevation.svg"), "w") as fh:
            fh.write(elevation(c["w"], c["h"], c["d"], c["title"], c["features"]))
        print(f'  wrote docs/design/vision/{c["stem"]}/elevation.svg')

    doc = [f'# Vision — Thermal Probe', "",
           "A handheld probe that logs temperature in a walk-in freezer for a "
           "week on one charge, readable with gloves on. Every image below "
           "comes from a parametric model, so the numbers are measured off the "
           "geometry rather than estimated.", "",
           "## The choice", "",
           "| | " + " | ".join(f'**{c["title"]}**' for c in CONCEPTS) + " |",
           "|---|" + "---|" * len(CONCEPTS),
           "| Envelope (mm) | " + " | ".join(
               f'{c["w"]} × {c["h"]} × {c["d"]}' for c in CONCEPTS) + " |",
           "| Volume (mm³) | " + " | ".join(
               f'{c["volume"]:,}' for c in CONCEPTS) + " |",
           "| Approx. mass (g) | " + " | ".join(
               f'{c["mass"]:,}' for c in CONCEPTS) + " |", ""]
    for c in CONCEPTS:
        doc += [f'## {c["title"]}', "", c["notes"], "",
                f'**What this one bets on:** {c["rationale"]}', "",
                f'**{c["w"]} × {c["h"]} × {c["d"]} mm** · {c["volume"]:,} mm³ · '
                f'~{c["mass"]} g at 1.4 g/cm³', "",
                f'![{c["title"]}](vision/{c["stem"]}/elevation.svg)', ""]
    with open(os.path.join(HERE, "docs", "design", "vision.md"), "w") as fh:
        fh.write("\n".join(doc))
    print("  wrote docs/design/vision.md")


# The shape strictdoc's JSON export flattens to, as req_trace.load() returns it.
REQS = [
    ("VIS-001", "A week in a freezer on one charge", "Agreed", [], "", [], "Inspection", ""),
    ("VIS-002", "Readable and operable wearing freezer gloves", "Agreed", [], "", [], "Inspection", ""),
    ("VIS-003", "Survives being dropped on a concrete floor", "Agreed", [], "", [], "Test", ""),

    ("SYS-001", "Battery life >= 7 d logging at 1 min intervals", "Agreed",
     ["VIS-001"], "", [], "Analysis", "7 d"),
    ("SYS-002", "Operating range -30 to +40 degC", "Agreed",
     ["VIS-001"], "", [], "Test", ""),
    ("SYS-003", "Display legible at 500 mm in 50 lx", "Agreed",
     ["VIS-002"], "", [], "Inspection", ""),
    ("SYS-004", "Survives 1.2 m drop onto concrete, 6 faces", "Agreed",
     ["VIS-003"], "", [], "Test", "1.2 m"),

    ("ELE-001", "Standby current <= 40 uA on the always-on rail", "Implemented",
     ["SYS-001"], "", ["hw/block-diagram.yaml"], "Simulation", "40 uA"),
    ("ELE-002", "Logging-cycle charge <= 180 uAh per sample", "Draft",
     ["SYS-001"], "", [], "Simulation", "180 uAh"),
    ("ELE-003", "ADC error <= 0.2 degC over -30 to +40 degC", "Draft",
     ["SYS-002"], "", [], "Test", "0.2 degC"),
    ("MEC-001", "Envelope <= 38 x 164 x 22 mm", "Verified",
     ["SYS-004"], "docs/design/vision.md, measured on the agreed model",
     ["cad/enclosure.py"], "Inspection", ""),
    ("MEC-002", "Enclosure withstands 1.2 m drop, 6 faces", "Draft",
     ["SYS-004"], "", [], "Test", ""),
    ("MEC-003", "Display window transmits >= 88% at 550 nm", "Draft",
     ["SYS-003"], "", [], "Inspection", "88%"),
    ("FW-001", "Sleep between samples, wake on RTC only", "Draft",
     ["SYS-001"], "", [], "Test", ""),
]


def build_requirements() -> None:
    import req_trace as rt
    reqs = [{"uid": u, "title": t, "doc": "Thermal Probe", "status": s,
             "verification": v, "evidence": e, "budget": b,
             "parents": list(p), "files": list(f)}
            for (u, t, s, p, e, f, v, b) in REQS]
    a = rt.analyse(reqs)
    out = os.path.join(HERE, "docs", "design")
    os.makedirs(out, exist_ok=True)
    rt.write_map(reqs, a, os.path.join(out, "requirements-map.svg"),
                 os.path.join(out, "requirements-map.drawio"))
    # The cached export the artifact generator reads when strictdoc is absent.
    with open(os.path.join(out, "requirements.json"), "w") as fh:
        json.dump({"requirements": reqs,
                   "summary": {k: a[k] for k in
                               ("total", "verified", "with_evidence",
                                "coverage_pct", "by_level")},
                   "findings": a["findings"]}, fh, indent=2)
    print("  wrote docs/design/requirements.json")


def main() -> int:
    os.chdir(HERE)
    print("Building the Thermal Probe fixture")
    build_vision()
    build_requirements()
    print("\nNow run, from this directory:")
    print("  plan-render        # docs/plan.{svg,md,drawio} and the README block")
    print("  block-diagram      # hw/block-diagram.drawio, docs/design/block-diagram.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
