"""Concept B — instrument. Squarer, chamfered, with a control detent."""
from build123d import *

TITLE = "B — Instrument"
NOTES = "Tight radii and a chamfered lip. Reads precise; costs more to mould."
MATERIAL = "graphite"

W, D, H = 66, 118, 17

_body = Box(W, D, H)
_body = fillet(_body.edges().filter_by(Axis.Z), radius=3.5)
_body = chamfer(_body.edges().group_by(Axis.Z)[-1], length=1.6)
_screen = Pos(0, 14, H / 2) * Box(54, 76, 1.4)
_dial = Pos(0, -44, H / 2) * Cylinder(radius=9, height=2.4)
PART = _body - _screen - _dial
