# What each format actually carries

Measured on this toolchain — build123d 0.11.1 on OCCT 7.9 — by exporting an
assembly and re-importing it, not from documentation.

| | Tree | Names | Colours | Placement | Editable joints |
|---|---|---|---|---|---|
| **STEP AP242** | yes | yes | yes | yes | **no** |
| **glTF / GLB** | yes | yes | yes | yes | **no** |
| **3MF** | yes | yes | yes | yes | **no** |
| **STL** | no | no | no | baked in | **no** |
| **FreeCAD `.FCStd`** | yes | yes | yes | yes | **yes** |

## STEP

`cad-export` writes AP242, not the AP214 build123d produces by default.

That is worth knowing if you ever write the export yourself:
`build123d.export_step` calls `STEPCAFControl_Controller.Init_s()` partway
through its own body, which resets the `write.step.schema` static back to its
default **after** any caller has set it. Setting the parameter before calling
`export_step` therefore appears to succeed — `SetCVal_s` returns True — and has
no effect on the file. `cad-export` drives `STEPCAFControl_Writer` directly and
sets the schema between the controller init and the transfer.

Verified by re-import: the tree, every label and every colour come back.

**What it does not carry is mates.** AP242 edition 2 defines kinematics; OCCT
does not write them and FreeCAD does not read them. There is currently no
portable file format that moves an editable constraint between CAD tools.

### The mate-datum convention

Since STEP does carry named solids at known locations, `cad-export` writes one
per joint: a 2 mm cross at the joint's own origin and orientation, labelled
`MATE_<part>_<joint>` and coloured magenta so it is obvious and easy to hide.

A CAD user opening the STEP then has something to snap to. Selecting a datum's
axis and mating it to another datum's axis is three clicks; finding the right
face on a part somebody else modelled is not.

Hide the `MATE_*` bodies before rendering or measuring. They are annotation.

## glTF / GLB

The node tree, node names and per-part colours all survive. Colours are written
linearised, which is correct for glTF and is why the numbers in the file do not
match the `Color(...)` you wrote.

This is the format for the interactive viewer on the review page. GitHub does
**not** render it in the blob view.

## STL

Geometry only — one merged mesh, no names, no colours, no tree.

Worth exporting anyway for exactly one reason: **GitHub renders `.stl` in an
interactive 3D viewer in the blob view**, up to 10 MB, and it is the only 3D
format it does render. That makes it the one file a reviewer can rotate and
zoom with nothing installed. Keep it coarse — it is for looking at — and say in
the review request that it is a review mesh, not a manufacturing one.

## 3MF

Neither build123d nor OCCT has a 3MF exporter, so `cad-export` writes one: it
is a zip of two small XML files, and it is the only *mesh* format that carries
part names and colours. Use it when a print or mesh workflow would otherwise
lose the assembly.

## FreeCAD

The only path where a constraint arrives alive. `<name>-freecad.py` imports the
STEP and creates `Assembly::JointFixed`, `JointRevolute`, `JointSlider`,
`JointCylindrical` or `JointBall` objects from `<name>-joints.json`, including
angle and length limits where the build123d joint declared a range.

Needs **FreeCAD 1.0 or newer** — the Assembly workbench does not exist before
that, and the macro says so and still saves the geometry rather than failing.

## joints.json

```json
{
  "name": "rim",
  "part": "shell",
  "type": "RigidJoint",
  "freecad_type": "Fixed",
  "position_mm": [0.0, 0.0, 8.8],
  "rotation_deg": [0.0, 0.0, 0.0],
  "connected_to": {"part": "lid", "joint": "seam"}
}
```

Readable by a person and by the macro. A `RevoluteJoint` additionally carries
`axis_origin_mm`, `axis_direction` and `angle_limits_deg`; a `LinearJoint`
carries `linear_limits_mm`.

This is the file to hand somebody working in a CAD tool the macro does not
cover. It says, in numbers, where every mate goes.

## The gate

`cad-export --check` fails on:

* a module exposing `PART` instead of `ASSEMBLY` — a single solid;
* a part with no label, which arrives as `Solid` in the tree;
* a part with no colour, which makes every render one flat shape;
* **no joints at all**, or a part no joint reaches — positioned by hand, so it
  will not follow the next changed dimension;
* duplicate part labels, which the CAD tree cannot tell apart;
* parts sharing solid volume, which is a real interference and not a
  rendering artefact.

None of those are opinions about style. Each one is a way the file is worse for
the person who has to open it.
