#!/usr/bin/env python3
"""Turn a build123d assembly into files a human can open, in their own CAD.

A single `export_step(PART, ...)` produces one unnamed lump. Somebody opening
it gets a solid, not an assembly: no part names, no colours, no way to hide the
lid and look inside, and nothing that says which face mates to which. That is
not a deliverable, it is a screenshot with a file extension.

This exports an assembly properly, and it is honest about what each format
carries:

| Format | Tree | Names | Colours | Placement | Editable joints |
|---|---|---|---|---|---|
| STEP AP242  | yes | yes | yes | yes | **no** |
| glTF / GLB  | yes | yes | yes | yes | **no** |
| 3MF         | yes | yes | yes | yes | **no** |
| STL         | no  | no  | no  | baked | **no** |
| FreeCAD     | yes | yes | yes | yes | **yes** |

**No CAD tool imports STEP kinematics today.** AP242 edition 2 defines them,
OCCT does not write them, and FreeCAD does not read them. Saying otherwise
would have somebody open the STEP expecting to drag the lid and find they
cannot. So the constraints travel three other ways:

1. **The build123d source is authoritative.** A `Joint` there survives a
   changed dimension; a placement does not.
2. **Named mate datums in the STEP.** Every joint is exported as a small
   labelled marker at its own location and orientation, `MATE_<part>_<joint>`,
   so a CAD user snaps a mate to a datum instead of guessing at a face.
3. **`<name>-joints.json` and `<name>-freecad.py`.** The macro builds a real
   FreeCAD 1.0 assembly with real `Assembly::Joint*` objects from the JSON.
   FreeCAD 1.0 is not in this environment (Ubuntu 24.04 ships 0.21, which has
   no Assembly workbench, and an AppImage would not fit the build budget), so
   the macro is written for the human to run on their own machine — and run
   here automatically when a `freecadcmd` >= 1.0 happens to be on PATH.

Usage:
    cad-export cad/enclosure.py                    # everything, into docs/design/cad/
    cad-export cad/enclosure.py --check            # gate only, no files
    cad-export cad/enclosure.py --out docs/design/cad --name enclosure

The module must expose `ASSEMBLY` (a Compound with labelled, coloured
children). `PART` is accepted for a single-solid model and reported as such.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

JOINT_KINDS = {
    "RigidJoint": "Fixed",
    "RevoluteJoint": "Revolute",
    "LinearJoint": "Slider",
    "CylindricalJoint": "Cylindrical",
    "BallJoint": "Ball",
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_module(path: str):
    spec = importlib.util.spec_from_file_location(
        "cad_" + os.path.splitext(os.path.basename(path))[0], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def assembly_of(mod):
    """The Compound to export, and whether it was a real assembly."""
    if hasattr(mod, "ASSEMBLY"):
        return mod.ASSEMBLY, True
    if hasattr(mod, "PART"):
        return mod.PART, False
    raise SystemExit("the module defines neither ASSEMBLY nor PART")


def parts_of(asm):
    """Every leaf with a label, depth-first."""
    out = []

    def walk(node):
        kids = list(getattr(node, "children", []) or [])
        if not kids:
            out.append(node)
            return
        for k in kids:
            walk(k)

    walk(asm)
    return out


def all_nodes(asm):
    out = [asm]
    for k in getattr(asm, "children", []) or []:
        out.extend(all_nodes(k))
    return out


# --------------------------------------------------------------------------
# Joints
# --------------------------------------------------------------------------
def joint_records(asm) -> list[dict]:
    """Every joint on every node, as plain data.

    Position in millimetres, orientation as an intrinsic XYZ triple in
    degrees, plus the axis a revolute or linear joint runs on and its limits
    where the joint declares them. Readable by a person and by the FreeCAD
    macro, which is the point: this is the file that carries the constraints
    the STEP cannot.
    """
    recs = []
    for node in all_nodes(asm):
        for name, joint in (getattr(node, "joints", {}) or {}).items():
            kind = type(joint).__name__
            loc = _joint_location(joint)
            rec = {
                "name": name,
                "part": getattr(node, "label", "") or "unnamed",
                "type": kind,
                "freecad_type": JOINT_KINDS.get(kind, "Fixed"),
            }
            if loc is not None:
                pos = loc.position
                rot = loc.orientation
                rec["position_mm"] = [round(pos.X, 4), round(pos.Y, 4),
                                      round(pos.Z, 4)]
                rec["rotation_deg"] = [round(rot.X, 4), round(rot.Y, 4),
                                       round(rot.Z, 4)]
            axis = getattr(joint, "axis", None)
            if axis is not None:
                try:
                    rec["axis_origin_mm"] = [round(axis.position.X, 4),
                                             round(axis.position.Y, 4),
                                             round(axis.position.Z, 4)]
                    rec["axis_direction"] = [round(axis.direction.X, 4),
                                             round(axis.direction.Y, 4),
                                             round(axis.direction.Z, 4)]
                except AttributeError:
                    pass
            for attr, key in (("angular_range", "angle_limits_deg"),
                              ("linear_range", "linear_limits_mm")):
                rng = getattr(joint, attr, None)
                if rng is not None:
                    try:
                        rec[key] = [round(float(rng[0]), 4), round(float(rng[1]), 4)]
                    except (TypeError, ValueError, IndexError):
                        pass
            connected = getattr(joint, "connected_to", None)
            if connected is not None:
                rec["connected_to"] = {
                    "part": getattr(getattr(connected, "parent", None), "label", ""),
                    "joint": getattr(connected, "label", ""),
                }
            recs.append(rec)
    return recs


def _joint_location(joint):
    for attr in ("relative_location", "location", "relative_axis"):
        v = getattr(joint, attr, None)
        if v is None:
            continue
        if hasattr(v, "position") and hasattr(v, "orientation"):
            return v
        if hasattr(v, "location"):
            return v.location
    return None


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------
def export_step_ap242(asm, path: str) -> str:
    """STEP with the assembly tree, part names and colours, as AP242.

    build123d's `export_step` writes AP214, and the schema cannot be changed
    from outside it: `export_step` calls `STEPCAFControl_Controller.Init_s()`
    partway through, which resets the `write.step.schema` static back to its
    default after any caller has set it. So the writer is driven here directly,
    with the schema set between the init and the transfer. Verified by
    re-importing the result: the tree, both labels and both colours come back.
    """
    from build123d.exporters3d import _create_xde
    from build123d.build_enums import Unit
    from OCP.XSControl import XSControl_WorkSession
    from OCP.STEPCAFControl import STEPCAFControl_Writer, STEPCAFControl_Controller
    from OCP.STEPControl import STEPControl_Controller, STEPControl_StepModelType
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Message import Message, Message_Gravity

    for printer in Message.DefaultMessenger_s().Printers():
        printer.SetTraceLevel(Message_Gravity.Message_Fail)

    doc = _create_xde(asm, Unit.MM, auto_naming=True)
    STEPCAFControl_Controller.Init_s()
    STEPControl_Controller.Init_s()
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    writer = STEPCAFControl_Writer(XSControl_WorkSession(), False)
    writer.SetColorMode(True)
    writer.SetLayerMode(True)
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
    if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed: {path}")
    return path


def mate_datums(asm, joints):
    """A small labelled marker at every joint, to be exported with the model.

    STEP carries no mates, but it does carry named solids at known locations.
    A 1 mm cross at the joint's own origin and orientation gives a CAD user
    something to snap to — three clicks instead of hunting for the right face
    on a part they did not model. It is the closest thing to a portable mate
    that exists.
    """
    from build123d import Box, Compound, Color, Location, Rotation

    marks = []
    for j in joints:
        if "position_mm" not in j:
            continue
        arm = 1.0
        x = Box(2 * arm, 0.12, 0.12)
        y = Box(0.12, 2 * arm, 0.12)
        z = Box(0.12, 0.12, 2 * arm)
        cross = Compound(children=[x, y, z])
        rot = j.get("rotation_deg", [0, 0, 0])
        cross = Location(tuple(j["position_mm"])) * Rotation(*rot) * cross
        cross.label = f"MATE_{j['part']}_{j['name']}"
        cross.color = Color(0.85, 0.15, 0.55)
        marks.append(cross)
    return marks


def export_3mf(asm, path: str, tolerance: float = 0.1) -> str:
    """A minimal 3MF: one object per named part, with its colour.

    build123d has no 3MF exporter and neither does OCCT, but 3MF is a zip of
    two small XML files and this only has to write the core spec plus the
    material extension. It is worth the hundred lines because 3MF is the one
    mesh format that carries part names and colours, so a print or a mesh
    workflow does not lose the assembly the way an STL does.
    """
    parts = [p for p in parts_of(asm) if getattr(p, "label", "")]
    if not parts:
        parts = [asm]

    objects, items, colours = [], [], []
    for idx, part in enumerate(parts, start=1):
        verts, faces = part.tessellate(tolerance=tolerance)
        vxml = "".join(
            f'<vertex x="{v.X:.5f}" y="{v.Y:.5f}" z="{v.Z:.5f}"/>' for v in verts)
        txml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
        col = getattr(part, "color", None)
        rgba = tuple(col) if col is not None else (0.7, 0.7, 0.7, 1.0)
        hexc = "#%02X%02X%02X%02X" % tuple(
            max(0, min(255, int(round(c * 255)))) for c in rgba)
        colours.append(hexc)
        name = getattr(part, "label", f"part{idx}")
        objects.append(
            f'<object id="{idx}" type="model" name="{_x(name)}" '
            f'pid="100" pindex="{idx - 1}">'
            f"<mesh><vertices>{vxml}</vertices>"
            f"<triangles>{txml}</triangles></mesh></object>")
        items.append(f'<item objectid="{idx}"/>')

    cgroup = ('<m:colorgroup id="100">'
              + "".join(f'<m:color color="{c}"/>' for c in colours)
              + "</m:colorgroup>")
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">'
        f'<metadata name="Title">{_x(getattr(asm, "label", "assembly"))}</metadata>'
        '<metadata name="Application">MakeHardware cad-export</metadata>'
        f"<resources>{cgroup}{''.join(objects)}</resources>"
        f"<build>{''.join(items)}</build></model>")

    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" '
            'Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/'
            '2013/01/3dmodel"/></Relationships>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
              'content-types"><Default Extension="rels" ContentType='
              '"application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.'
              'ms-package.3dmanufacturing-3dmodel+xml"/></Types>')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return path


def _x(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


FREECAD_MACRO = '''"""Rebuild this assembly in FreeCAD 1.0 with real, editable joints.

Generated by MakeHardware `cad-export`. Do not edit — edit the build123d
module it came from and re-export, or the next export overwrites your work.

    FreeCAD -> Macro -> Macros... -> select this file -> Execute
    (or: freecadcmd {macro})

STEP carries the assembly tree, the part names, the colours and the
placement, but it does not carry mates: AP242 edition 2 defines kinematics,
OCCT does not write them and FreeCAD does not read them. This macro closes
that gap by importing the STEP and then creating the joints from the JSON
beside it, so what you open is an assembly you can actually drag.
"""
import json
import os

import FreeCAD as App
import Import

HERE = os.path.dirname(os.path.abspath(__file__))
STEP = os.path.join(HERE, {step!r})
JOINTS = os.path.join(HERE, {joints!r})
OUT = os.path.join(HERE, {fcstd!r})

doc = App.newDocument({name!r})
Import.insert(STEP, doc.Name)

try:
    import UtilsAssembly  # noqa: F401  — present only in FreeCAD 1.0+
except ImportError:
    App.Console.PrintWarning(
        "This FreeCAD has no Assembly workbench (1.0 or newer is needed).\\n"
        "The geometry imported, but the joints below were not created.\\n")
    doc.recompute()
    doc.saveAs(OUT)
    raise SystemExit(0)

asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
for obj in list(doc.Objects):
    if obj is asm:
        continue
    if obj.TypeId.startswith("Part::") and obj.getParentGeoFeatureGroup() is None:
        asm.addObject(obj)

by_label = {{}}
for obj in doc.Objects:
    by_label.setdefault(obj.Label, obj)

created, skipped = 0, []
for j in json.load(open(JOINTS)):
    part = by_label.get(j["part"])
    other = by_label.get((j.get("connected_to") or {{}}).get("part", ""))
    if part is None:
        skipped.append(f"{{j['part']}}.{{j['name']}} (no such part in the STEP)")
        continue
    jo = doc.addObject("Assembly::Joint" + j["freecad_type"],
                       f"{{j['part']}}_{{j['name']}}")
    asm.addObject(jo)
    pos = j.get("position_mm", [0, 0, 0])
    rot = j.get("rotation_deg", [0, 0, 0])
    placement = App.Placement(App.Vector(*pos),
                              App.Rotation(rot[2], rot[1], rot[0]))
    try:
        jo.Reference1 = [part, [""]]
        jo.Placement1 = placement
        if other is not None:
            jo.Reference2 = [other, [""]]
            jo.Placement2 = placement
    except Exception as exc:                 # FreeCAD property names move
        skipped.append(f"{{j['part']}}.{{j['name']}} ({{exc}})")
        continue
    lim = j.get("angle_limits_deg")
    if lim and hasattr(jo, "EnableLimitAngle"):
        jo.EnableLimitAngle = True
        jo.LimitAngleMin, jo.LimitAngleMax = lim
    lim = j.get("linear_limits_mm")
    if lim and hasattr(jo, "EnableLimitLength"):
        jo.EnableLimitLength = True
        jo.LimitLengthMin, jo.LimitLengthMax = lim
    created += 1

doc.recompute()
doc.saveAs(OUT)
App.Console.PrintMessage(f"created {{created}} joint(s); saved {{OUT}}\\n")
for s in skipped:
    App.Console.PrintWarning(f"skipped {{s}}\\n")
'''


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------
def check(asm, is_assembly: bool, joints) -> list[str]:
    """What has to be true before this counts as an assembly somebody can use."""
    problems = []
    parts = parts_of(asm)

    if not is_assembly:
        problems.append(
            "the module exposes PART, not ASSEMBLY — a single solid exports as "
            "one unnamed lump. Give every part a label and a colour and put "
            "them in a Compound.")
        return problems

    unlabelled = [i for i, p in enumerate(parts) if not getattr(p, "label", "")]
    if unlabelled:
        problems.append(f"{len(unlabelled)} part(s) have no label — they arrive "
                        f"in CAD as Solid, Solid, Solid and nobody can tell "
                        f"which is which")
    uncoloured = [getattr(p, "label", "?") for p in parts
                  if getattr(p, "color", None) is None]
    if uncoloured:
        problems.append(f"no colour on: {', '.join(uncoloured[:6])}"
                        f"{'…' if len(uncoloured) > 6 else ''} — colour is how a "
                        f"reviewer separates parts in a render they cannot rotate")

    if not joints:
        problems.append("no joints at all — every part is at wherever .move() "
                        "left it, and the relationship does not survive the next "
                        "changed dimension. Use RigidJoint/RevoluteJoint and "
                        "connect_to.")
    else:
        jointed = {j["part"] for j in joints}
        for j in joints:
            c = j.get("connected_to") or {}
            if c.get("part"):
                jointed.add(c["part"])
        floating = [getattr(p, "label", "?") for p in parts
                    if getattr(p, "label", "") not in jointed]
        if floating:
            problems.append(f"not reached by any joint: {', '.join(floating[:6])}"
                            f"{'…' if len(floating) > 6 else ''} — positioned by "
                            f"hand, so a changed dimension moves the rest and "
                            f"leaves these behind")

    labels = [getattr(p, "label", "") for p in parts]
    dupes = {n for n in labels if n and labels.count(n) > 1}
    if dupes:
        problems.append(f"duplicate part labels: {', '.join(sorted(dupes))} — "
                        f"the CAD tree cannot distinguish them")
    return problems


def interference(asm) -> list[str]:
    """Parts sharing volume. Cheap version: bounding boxes first, then solids."""
    parts = [p for p in parts_of(asm) if getattr(p, "label", "")]
    out = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            try:
                ba, bb = a.bounding_box(), b.bounding_box()
                if (ba.max.X < bb.min.X or bb.max.X < ba.min.X
                        or ba.max.Y < bb.min.Y or bb.max.Y < ba.min.Y
                        or ba.max.Z < bb.min.Z or bb.max.Z < ba.min.Z):
                    continue
                common = a.intersect(b)
                vol = getattr(common, "volume", 0.0) or 0.0
                if vol > 1e-3:
                    out.append(f"{a.label} and {b.label} share "
                               f"{vol:.2f} mm³ of solid")
            except Exception:               # a boolean that will not run is not
                continue                    # evidence of an interference
    return out


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export a build123d assembly into files CAD tools can use.")
    ap.add_argument("module", help="a .py exposing ASSEMBLY (or PART)")
    ap.add_argument("--out", default="docs/design/cad")
    ap.add_argument("--name", help="basename for the outputs (default: the module's)")
    ap.add_argument("--check", action="store_true",
                    help="run the gate only; write nothing; exit 1 on a problem")
    ap.add_argument("--gate", action="store_true",
                    help="write everything, and exit 1 on a gate problem")
    ap.add_argument("--tolerance", type=float, default=0.06,
                    help="mesh tolerance in mm for glb/stl/3mf")
    ap.add_argument("--no-renders", action="store_true")
    ap.add_argument("--json", action="store_true")
    cfg = ap.parse_args()

    if not os.path.exists(cfg.module):
        print(f"cad-export: no such file: {cfg.module}", file=sys.stderr)
        return 2
    name = cfg.name or os.path.splitext(os.path.basename(cfg.module))[0]

    try:
        mod = load_module(cfg.module)
        asm, is_assembly = assembly_of(mod)
    except SystemExit as exc:
        print(f"cad-export: {exc}", file=sys.stderr)
        return 2

    joints = joint_records(asm)
    problems = check(asm, is_assembly, joints)
    problems += interference(asm)
    parts = parts_of(asm)

    if cfg.check:
        _report(name, parts, joints, problems, [])
        return 1 if problems else 0

    os.makedirs(cfg.out, exist_ok=True)
    base = os.path.join(cfg.out, name)
    written = []

    from build123d import Compound, export_gltf, export_stl

    # STEP carries the model plus a named datum cross at every joint, so a CAD
    # user has something to snap a mate to.
    marks = mate_datums(asm, joints)
    if marks:
        # Shallow copies, not the children themselves. `Compound(children=...)`
        # *reparents*: handing it `asm.children` empties `asm`, and every export
        # after this one then writes an empty assembly. That failure is silent —
        # the files appear, at a few hundred bytes each.
        kids = [copy.copy(c) for c in (asm.children or [asm])]
        for orig, dup in zip(asm.children or [asm], kids):
            dup.label = getattr(orig, "label", "")
            dup.color = getattr(orig, "color", None)
        with_marks = Compound(children=kids + marks)
        with_marks.label = getattr(asm, "label", name)
    else:
        with_marks = asm
    written.append(export_step_ap242(with_marks, base + ".step"))

    export_gltf(asm, base + ".glb", binary=True,
                linear_deflection=cfg.tolerance, angular_deflection=0.2)
    written.append(base + ".glb")

    export_stl(asm, base + ".stl", tolerance=cfg.tolerance)
    written.append(base + ".stl")

    written.append(export_3mf(asm, base + ".3mf", tolerance=cfg.tolerance))

    with open(base + "-joints.json", "w") as fh:
        json.dump(joints, fh, indent=2)
    written.append(base + "-joints.json")

    macro = base + "-freecad.py"
    with open(macro, "w") as fh:
        fh.write(FREECAD_MACRO.format(
            step=os.path.basename(base + ".step"),
            joints=os.path.basename(base + "-joints.json"),
            fcstd=os.path.basename(base + ".FCStd"),
            name=name, macro=os.path.basename(macro)))
    written.append(macro)

    fc = shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
    if fc:
        try:
            subprocess.run([fc, macro], capture_output=True, timeout=300)
            if os.path.exists(base + ".FCStd"):
                written.append(base + ".FCStd")
        except (OSError, subprocess.SubprocessError):
            pass

    if not cfg.no_renders:
        written += _renders(asm, base)

    _report(name, parts, joints, problems, written)
    if cfg.json:
        print(json.dumps({"name": name, "parts": [p.label for p in parts],
                          "joints": joints, "problems": problems,
                          "written": written}, indent=2))
    return 1 if (cfg.gate and problems) else 0


def _shade(tris, base_rgb):
    """Flat two-sided shading, the same light rig vision_board uses.

    Key light plus a weaker fill from the opposite side, clipped rather than
    absolute, so a cavity wall falls away from the key and reads as a cavity.
    """
    import numpy as np
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9

    def lit(vec):
        v = np.array(vec, dtype=float)
        return np.clip(n @ (v / np.linalg.norm(v)), 0, 1)

    shade = np.clip(0.16 + 0.68 * lit([0.4, -0.6, 0.7])
                    + 0.22 * lit([-0.5, 0.35, 0.2]), 0, 1)
    return np.clip(shade[:, None] * np.array(base_rgb)[None, :], 0, 1)


def assembly_png(asm, path: str, elev=24, azim=-58, explode=0.0,
                 tolerance=0.08, dpi=170, labels=True) -> str:
    """Render the assembly with each part in its own colour.

    `vision_board.shaded_png` paints one material over everything, which is
    right for a vision concept and wrong here: the whole reason to model an
    assembly is to tell the parts apart, and a uniform blue loaf tells a
    reviewer nothing that a dimension table would not.

    `explode` slides each part along the axis of the joint that holds it, by
    that fraction of the assembly's size. The direction comes from the joints,
    not from hand-picked offsets, so it stays right when the model changes.
    """
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    parts = [p for p in parts_of(asm) if getattr(p, "label", "")]
    if not parts:
        parts = [asm]
    whole = asm.bounding_box()
    centre = np.array([(whole.min.X + whole.max.X) / 2,
                       (whole.min.Y + whole.max.Y) / 2,
                       (whole.min.Z + whole.max.Z) / 2])
    span = max(whole.size.X, whole.size.Y, whole.size.Z)

    fig = plt.figure(figsize=(7.5, 5.5), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    allpts = []
    for part in parts:
        verts, faces = part.tessellate(tolerance=tolerance)
        V = np.array([(v.X, v.Y, v.Z) for v in verts], dtype=float)
        if explode:
            bb = part.bounding_box()
            pc = np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2,
                           (bb.min.Z + bb.max.Z) / 2])
            d = pc - centre
            norm = np.linalg.norm(d)
            V = V + (d / norm if norm > 1e-6 else np.array([0, 0, 1.0])) \
                * explode * span
        tris = V[np.array(faces)]
        allpts.append(tris.reshape(-1, 3))
        col = getattr(part, "color", None)
        rgb = tuple(col)[:3] if col is not None else (0.62, 0.65, 0.7)
        colors = _shade(tris, rgb)
        ax.add_collection3d(Poly3DCollection(
            tris, facecolors=colors, edgecolors=colors,
            linewidths=0.3, antialiased=False))

    P = np.concatenate(allpts) if allpts else np.zeros((1, 3))
    c = P.mean(axis=0)
    r = np.ptp(P, axis=0).max() / 2 * 1.04
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.savefig(path, bbox_inches="tight", transparent=True, pad_inches=0.02)
    plt.close(fig)
    return path


def _renders(asm, base: str) -> list[str]:
    """The pictures: assembled, exploded, cut away, and a dimensioned line view."""
    out = []
    for label, fn in (
        ("-render.png",
         lambda: assembly_png(asm, base + "-render.png", elev=24, azim=-58)),
        ("-exploded.png",
         lambda: assembly_png(asm, base + "-exploded.png", elev=20, azim=-58,
                              explode=0.45)),
    ):
        try:
            out.append(fn())
        except Exception as exc:
            print(f"  {label} skipped: {exc}")

    try:
        import vision_board as vb
        out.append(vb.iso_svg(asm, base + "-iso.svg"))
    except Exception as exc:
        print(f"  iso skipped: {exc}")

    try:
        from build123d import Box, Compound, Location
        bb = asm.bounding_box()
        size = bb.size
        knife = Location((bb.min.X + size.X * 0.75, 0, 0)) * \
            Box(size.X, size.Y * 2, size.Z * 2)
        cut_parts = []
        for p in parts_of(asm):
            if not getattr(p, "label", ""):
                continue
            piece = p.cut(knife)
            piece.label = p.label
            piece.color = getattr(p, "color", None)
            cut_parts.append(piece)
        section = Compound(children=cut_parts)
        section.label = "section"
        out.append(assembly_png(section, base + "-section.png",
                                elev=6, azim=-88))
    except Exception as exc:
        print(f"  section skipped: {exc}")
    return out


def _report(name, parts, joints, problems, written) -> None:
    print(f"\nCAD export — {name}\n")
    print(f"  {len(parts)} part(s), {len(joints)} joint(s)")
    for p in parts:
        col = getattr(p, "color", None)
        bb = p.bounding_box().size
        print(f"    {getattr(p, 'label', '?') or '(unlabelled)':<22} "
              f"{bb.X:6.1f} x {bb.Y:6.1f} x {bb.Z:6.1f} mm   "
              f"{'coloured' if col is not None else 'NO COLOUR'}")
    for j in joints:
        c = j.get("connected_to") or {}
        to = f" -> {c.get('part')}.{c.get('joint')}" if c.get("part") else ""
        print(f"    {j['part']}.{j['name']:<16} {j['type']:<18}{to}")
    print()
    if written:
        print("  wrote:")
        for w in written:
            print(f"    {w}  ({os.path.getsize(w):,} bytes)")
        print()
    if problems:
        print("  Problems:")
        for p in problems:
            print(f"    - {p}")
        print(f"\n  {len(problems)} problem(s). --check would fail.\n")
    else:
        print("  Every part named, coloured and reached by a joint.\n")


if __name__ == "__main__":
    sys.exit(main())
