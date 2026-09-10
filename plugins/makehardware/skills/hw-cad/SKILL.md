---
name: hw-cad
description: Model mechanical parts as a real assembly - labelled, coloured, held together by joints rather than by coordinates - and export files a human can open and manipulate in their own CAD tool. Use when modelling an enclosure, a bracket, a fixture or any multi-part mechanical design, when a CAD file has to go to somebody else, when asked for a STEP or a 3D model, and when a model needs a render, a section or an exploded view for review.
---

# Modelling for somebody else's CAD tool

The default way a model gets written is one `BuildPart`, one `PART`, one
`export_step`. What arrives at the other end is a solid: no part names, no
colours, no way to hide the lid and look inside, and nothing that says which
face mates to which. That is a screenshot with a file extension.

Two rules make the difference, and `cad-export --check` enforces both.

## 1. Model an assembly, and give every part a name and a colour

```python
shell = _shell.part
shell.label = "shell"                       # what it is called in the CAD tree
shell.color = Color(0.16, 0.20, 0.26)       # how a reviewer tells it apart

ASSEMBLY = Compound(children=[shell, lid, board, cell])
ASSEMBLY.label = "thermal-probe-enclosure"
```

Labels and colours survive the STEP, the GLB and the 3MF. Without them the
tree reads `Solid, Solid, Solid` and every render is one uniform colour, which
is the same as no render.

## 2. Position by joint, never by `.move()`

```python
RigidJoint("rim",  shell, Location((0, 0, DEPTH * SPLIT)))
RigidJoint("seam", lid,   Location((0, 0, 0)))
shell.joints["rim"].connect_to(lid.joints["seam"])
```

A joint is a *relationship*; a `.move()` is a coordinate. Raise `WALL` by
0.2 mm and every jointed part follows; a hand-placed part stays exactly where
it was and quietly ends up inside a wall. Nothing warns you, and the render
still looks fine. `cad-export --check` fails on a part no joint reaches, for
exactly that reason.

Use the joint that describes the real freedom: `RigidJoint` for something
bolted, `RevoluteJoint` for a hinge (with its angular range),
`LinearJoint` for a slide, `CylindricalJoint`, `BallJoint`. The type is what
gets written into `joints.json` and turned into a real FreeCAD joint.

## Export

```bash
cad-export cad/enclosure.py --out docs/design/cad     # everything
cad-export cad/enclosure.py --check                   # the gate, writes nothing
```

| File | For |
|---|---|
| `.step` | **The CAD deliverable.** AP242, assembly tree, part names, colours, placement, plus a named datum cross at every joint |
| `.glb` | The interactive viewer on the review page — node tree, names and colours preserved |
| `.stl` | GitHub's own 3D viewer, which renders `.stl` in the blob view and nothing else |
| `.3mf` | Print and mesh workflows, with part names and colours intact |
| `-joints.json` | Every joint: type, parts, position, orientation, axis, limits |
| `-freecad.py` | A macro that rebuilds the assembly in FreeCAD 1.0 **with real joints** |
| `-render.png`, `-exploded.png`, `-section.png`, `-iso.svg` | The pictures a review needs |

The exploded view slides each part along the axis of the joint holding it, so
it stays correct when the model changes. A hand-picked offset does not.

## The thing to be honest about: STEP carries no mates

STEP carries the tree, the names, the colours and the placement. It does
**not** carry editable constraints. AP242 edition 2 defines kinematics, OCCT
does not write them, and FreeCAD does not read them. Telling somebody
otherwise has them open the file expecting to drag the lid and find they
cannot.

So the constraints travel three other ways, and the review request should say
which one you mean:

1. **The build123d module is authoritative.** It is the only place the
   relationship survives a changed number.
2. **Named mate datums in the STEP.** Every joint is exported as a small
   labelled cross, `MATE_<part>_<joint>`, at its own location and orientation.
   A CAD user snaps a mate to a datum in three clicks instead of hunting for
   the right face on a part they did not model.
3. **`-freecad.py`.** Run it in FreeCAD 1.0 (Macro → Macros… → Execute) and it
   imports the STEP and builds real `Assembly::Joint*` objects from the JSON.
   That is the one path where the constraints are live and draggable.

FreeCAD is not installed here — Ubuntu 24.04 ships 0.21, which has no Assembly
workbench, and an AppImage would not fit the environment build budget. So the
macro is written for the human's own machine, and run automatically only if a
`freecadcmd` 1.0 or newer happens to be on `PATH`.

`references/assemblies.md` has the full format table and the mate-datum
convention.

## For review

Commit the renders and the STL — GitHub shows `.stl` in an interactive viewer,
so that is the one file a human can rotate without installing anything, and it
beats any static image. Say in the request that it is a review mesh.

Put the GLB on the review page, where `review-artifact` embeds it in a
pan-and-zoom viewer with the parts in their own colours.

A **cross-section is usually the most informative single image** of an
enclosure: it shows the wall thicknesses, the internal clearances and where the
board actually sits, which is the one view a 3D viewer will not give by
default. `cad-export` writes one every time.

## Working with the build123d MCP server

Where the `build123d` MCP server is available, build there — it keeps a live
session, so you can `measure()` after every boolean and `render_view()` to look
at what you just made, instead of re-running a script and hoping. Write the
finished model back out as a module with `ASSEMBLY` in it, and run
`cad-export --check` over that. The module is what gets committed and reviewed;
the session is scratch.
