# Stackup, planes and return paths

Decided before the first footprint is placed. Changing it later is a re-route.

## Choosing a layer count

| Layers | Use it when | Arrangement |
|---|---|---|
| 2 | Nothing faster than a few MHz, no switching converter, cost dominates | Signal / ground pour. Every signal on top, an uninterrupted pour below. |
| 4 | The default for anything with an MCU, a switcher or a bus | Signal / **GND** / power / signal. |
| 6 | Two or more high-speed interfaces, or a dense BGA | Signal / GND / signal / signal / GND / signal. |

**Four layers, arranged signal-ground-power-signal, is the answer for most
boards** and it is worth the extra few dollars long before it is worth the
argument. The second layer being a solid, unbroken ground plane is what makes
every other rule in this file work.

The seductive mistake is signal / power / ground / signal, which puts each
signal layer next to a plane that is chopped into rail-shaped islands, so half
the signals have no continuous return. Do not.

## Reference planes

Every signal layer must have a plane layer immediately adjacent to it. That
plane is the return path; without one, return current finds its own way and the
loop it makes is the antenna.

`pcb-lint`'s `PCB-REFPLANE` checks the declared layer types and the pours. It
is suppressed on two-layer boards unless `--strict`, because there a signal
layer with a pour opposite it is the correct arrangement.

## Rules that follow from having a plane

**Never route a fast signal across a split in its reference plane.** The return
current has to go around the split, and the loop is the length of the detour. If
a split is unavoidable, route the signal around it too, or bridge it with a
stitching capacitor right where the signal crosses.

**Every signal via needs a return via.** A signal changing layers changes its
reference plane; the return has to change with it. A ground stitching via within
a couple of millimetres of the signal via does that. Without it, the return goes
to the nearest connection between the two planes, which may be centimetres away.

**Do not fragment the ground plane with traces.** A ground plane with a track
routed through it is two ground planes. If a plane layer must carry a signal,
route it where nothing above or below needs the return.

**Stitch the planes at the board edge and around any high-current loop.** Vias
every few millimetres. It costs nothing and it is what stops the board edge
radiating.

## Impedance

Anything that is a transmission line — USB, Ethernet, a display's differential
pairs, anything above about 50 MHz — needs a controlled-impedance stackup, and
that means the fabricator's stackup, not a guess. Ask them for it, put the
dielectric thicknesses into the KiCad stackup, and set the trace widths from
their calculator, not from a rule of thumb.

Put the resulting stackup in the review as a table:

| Layer | Type | Copper | Dielectric to next | Reference |
|---|---|---|---|---|
| F.Cu | signal | 35 µm | 0.20 mm prepreg | In1.Cu |
| In1.Cu | **GND** | 35 µm | 1.10 mm core | — |
| In2.Cu | power | 35 µm | 0.20 mm prepreg | — |
| B.Cu | signal | 35 µm | — | In2.Cu |

A reviewer can find a missing reference plane in that table in five seconds and
cannot find it in a render at all.

## Copper thickness and current

1 oz (35 µm) is the default. A 0.25 mm track in 1 oz outer copper carries about
1 A at a 10 °C rise; a 1 mm track about 3 A. Inner layers are worse — roughly
half — because there is no air to convect into.

Two consequences worth holding:

* **A power net's final track width is a thermal number, and it is usually far
  wider than a router can enter a pad with.** Route at pad width, widen
  afterwards, and record the target width in the layout notes so the widening
  is not forgotten. `templates/kicad/konnect-house.json` has a
  `final_track_width_mm` field for exactly this.
* **Vias carry current too.** A 0.3 mm via is good for roughly 1 A. Parallel
  them on a power path; one via is a fuse.
