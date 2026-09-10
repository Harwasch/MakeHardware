"""Thermal Probe enclosure — an assembly, not a solid.

MEC-001 caps the envelope at 38 x 164 x 22 mm. This module is the interface:
the board outline and the cell pocket are published from here, and the
electrical side treats them as fixed.

Written as four labelled, coloured parts held together by joints rather than
by `.move()` calls. That is not style. A joint survives a changed dimension —
raise `WALL` and the lid, the board and the cell all stay where they belong;
a hand-placed part stays at the coordinate it was put at and quietly ends up
inside a wall. `cad-export --check` fails on a part no joint reaches, for
exactly this reason.

    cad-export cad/enclosure.py --out docs/design/cad
"""
from build123d import *

# Agreed at the vision review, 2026-08-12. Do not change without re-opening it.
WIDTH, HEIGHT, DEPTH = 38.0, 164.0, 22.0
WALL = 1.8
CORNER_R = 6.0
SPLIT = 0.40                     # lid/shell split, as a fraction of DEPTH
LID_H = DEPTH * (1 - SPLIT)

# Published interfaces. The electrical side reads these; nothing else may.
BOARD_OUTLINE = (WIDTH - 2 * WALL - 1.0, 96.0)    # 33.4 x 96 mm
BOARD_T = 1.6
CELL_POCKET = (30.0, 50.0, 3.8)                   # LP503035 plus 0.3 mm clearance
BOARD_Z = DEPTH * SPLIT - 4.0                     # standoff height above the floor

# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------
with BuildPart() as _shell:
    with BuildSketch():
        RectangleRounded(WIDTH, HEIGHT, CORNER_R)
    extrude(amount=DEPTH * SPLIT)
    offset(amount=-WALL, openings=_shell.faces().sort_by(Axis.Z)[-1])

with BuildPart() as _lid:
    with BuildSketch():
        RectangleRounded(WIDTH, HEIGHT, CORNER_R)
    extrude(amount=LID_H)
    offset(amount=-WALL, openings=_lid.faces().sort_by(Axis.Z)[0])

with BuildPart() as _board:
    with BuildSketch():
        Rectangle(*BOARD_OUTLINE)
    extrude(amount=BOARD_T)

with BuildPart() as _cell:
    with BuildSketch():
        Rectangle(CELL_POCKET[0], CELL_POCKET[1])
    extrude(amount=CELL_POCKET[2])

shell = _shell.part
shell.label = "shell"
shell.color = Color(0.16, 0.20, 0.26)

lid = _lid.part
lid.label = "lid"
lid.color = Color(0.82, 0.36, 0.12)

board = _board.part
board.label = "pcb"
board.color = Color(0.05, 0.42, 0.28)

cell = _cell.part
cell.label = "cell"
cell.color = Color(0.72, 0.72, 0.75)

# --------------------------------------------------------------------------
# Joints — the relationships, not the coordinates
# --------------------------------------------------------------------------
# The shell's own datum: the inside floor, on the centreline. Every other part
# is placed relative to this, so moving the split or thickening the wall moves
# everything that should move and nothing that should not.
RigidJoint("floor", shell, Location((0, 0, WALL)))
RigidJoint("rim", shell, Location((0, 0, DEPTH * SPLIT)))

RigidJoint("seam", lid, Location((0, 0, 0)))
shell.joints["rim"].connect_to(lid.joints["seam"])

RigidJoint("underside", board, Location((0, 0, 0)))
RigidJoint("standoffs", shell, Location((0, 18.0, BOARD_Z)))
shell.joints["standoffs"].connect_to(board.joints["underside"])

RigidJoint("base", cell, Location((0, 0, 0)))
RigidJoint("cell_bay", shell, Location((0, -46.0, WALL)))
shell.joints["cell_bay"].connect_to(cell.joints["base"])

ASSEMBLY = Compound(children=[shell, lid, board, cell])
ASSEMBLY.label = "thermal-probe-enclosure"

# Kept so anything still expecting a single solid keeps working.
PART = shell
TITLE = "Enclosure, rev C"
NOTES = ("Envelope frozen at the vision review. Split at 40% of depth; the "
         "lid is the long half so the seam falls below the display.")
