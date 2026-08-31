"""Thermal Probe enclosure — envelope frozen from the agreed vision concept.

MEC-001 caps the envelope at 38 x 164 x 22 mm. This module is the interface:
the board outline and the cell pocket are published from here, and the
electrical side treats them as fixed.
"""
from build123d import *

# Agreed at the vision review, 2026-08-12. Do not change without re-opening it.
WIDTH, HEIGHT, DEPTH = 38.0, 164.0, 22.0
WALL = 1.8
CORNER_R = 6.0

# Published interfaces
BOARD_OUTLINE = (WIDTH - 2 * WALL - 1.0, 96.0)   # 33.4 x 96 mm
CELL_POCKET = (30.0, 50.0, 3.8)                   # LP503035 plus 0.3 mm clearance

with BuildPart() as shell:
    with BuildSketch() as outline:
        RectangleRounded(WIDTH, HEIGHT, CORNER_R)
    extrude(amount=DEPTH)
    offset(amount=-WALL, openings=shell.faces().sort_by(Axis.Z)[-1])

PART = shell.part
TITLE = "Enclosure, rev C"
NOTES = "Envelope frozen at the vision review. Split line at 40% depth."
