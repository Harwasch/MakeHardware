"""Concept A — soft slab. Rounded, pocketable, screen-forward."""
from build123d import *

TITLE = "A — Soft slab"
NOTES = "Continuous fillet, screen flush to the top face. Reads friendly."
MATERIAL = "cobalt"

W, D, H = 70, 120, 14

_body = Box(W, D, H)
_body = fillet(_body.edges().filter_by(Axis.Z), radius=9)
_body = fillet(_body.edges().group_by(Axis.Z)[-1], radius=2.0)
_screen = Pos(0, 12, H / 2) * Box(56, 80, 1.2)
PART = _body - _screen
