# CAD

build123d models. Each file defines the geometry as code so a changed number is
a re-render, not a redraw.

**Model an assembly, not a solid.** Every part gets a `label` and a `color`,
and parts are positioned by `Joint`s rather than by `.move()` — a joint is a
relationship and survives a changed dimension, a coordinate does not. Expose
the whole thing as `ASSEMBLY`.

```bash
cad-export cad/enclosure.py --check      # the gate: labels, colours, joints
cad-export cad/enclosure.py --out docs/design/cad --name enclosure
```

That writes the STEP (AP242, assembly tree, part names, colours, and a named
datum at every joint), a GLB for the review page's orbit viewer, an STL for
GitHub's own 3D viewer, a 3MF for print, `joints.json`, a FreeCAD 1.0 macro
that rebuilds the assembly with **real, draggable joints**, and the renders:
assembled, exploded, sectioned and isometric.

STEP carries the tree, the names, the colours and the placement. It does not
carry mates — no CAD tool imports STEP kinematics today. That is what the JSON
and the macro are for. See the `hw-cad` skill.

Link each model back to the requirement it realises with a `File` relation in
`requirements/`.
