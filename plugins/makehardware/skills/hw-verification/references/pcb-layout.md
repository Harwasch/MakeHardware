# PCB placement, routing and fabrication

Every item here cost hours on a real board, and every one of them was
diagnosed as something else first — board density, outline geometry, keepouts,
layer types — because the actual cause is invisible from where you are
standing. Work the checks in order. They are cheap; the misdiagnoses are not.

---

## 0. Which tool drives the board

**Konnect's PCB half needs a live KiCad.** `check_kicad_ui` reporting
`ipc_responsive: false` means the IPC tools will not work, and the socket path
is read from `KICAD_API_SOCKET` or `konnect-settings.json` **only at server
start** — so enabling KiCad's API server, starting Xvfb and launching pcbnew
inside the session does not fix it without restarting the MCP server.

For scripted layout, use **KiCad's own `pcbnew` Python API** instead. It is
the same object model that Konnect drives, so this is not text manipulation of
a `.kicad_pcb`, which is never acceptable:

```bash
/usr/lib/kicad/bin/python -c "import pcbnew; print(pcbnew.Version())"
# or wherever the KiCad 10 install put it:
python3 -c "import pcbnew" 2>/dev/null || ls /usr/lib/kicad*/bin/python*
```

Konnect's schematic half is file-based and works without a running KiCad.
That distinction is the one to hold on to: **schematic, file-based; board,
live or `pcbnew`.**

---

## 1. Before you place: check the net classes against the footprints

Nothing in KiCad warns you when a net class asks for something the parts on
that net cannot physically accept. It is not an error — it is simply
unroutable, and it presents as a router that returns almost every connection
as a failure with no explanation.

Two checks, both arithmetic:

**Track width against pad width.** A `Power` class at 1.20 mm and a `Rail`
class at 0.40 mm are correct current-carrying widths and both are impossible
to route: a QFN pin pad is 0.25 mm wide and an 0402 pad 0.5 mm, and a router
will not neck down to enter them. This is what "180 of 234 connections
unroutable" looks like.

**Clearance against pad pitch.** A `Power` class clearance of 0.30 mm against
a VSON-10's 0.255 mm pad-to-pad gap violates itself *inside the footprint*,
before a track exists. The part becomes unreachable and DRC reports clearance
errors within a component you have not touched.

```python
import pcbnew
board = pcbnew.LoadBoard("hw/probe.kicad_pcb")
for fp in board.Footprints():
    for pad in fp.Pads():
        net = pad.GetNetname()
        w = min(pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y))
        # compare w against the track width of the class carrying `net`,
        # and the smallest pad-to-pad gap in `fp` against its clearance
```

**The fix is to route at pad width and restore the carrying width
afterwards.** Set the class to something the pads accept, route, then widen
the tracks on the power nets and re-run DRC. Do not lower the current-carrying
width and leave it there — record in the layout notes what the final widths
must be, and check them at the end.

## 2. Run DRC on the placed, unrouted board

Before there is a single track. It found 721 errors on one board — three of
them real defects — and every one of those three would otherwise have been
found after routing, when fixing them means re-routing.

```bash
kicad-cli pcb drc hw/probe.kicad_pcb --output build/drc-placed.rpt \
    --severity-error --severity-warning
```

Placement errors are cheap; routed-board errors are not. Read the report
before you route, not after.

## 3. Thermal-via footprint variants collide through the board

A `_ThermalVias` footprint variant contains a via array under its exposed pad.
Those vias **punch through to the other side** and land on whatever is there —
on one board, 47 shorting pairs against a MOSFET drain pad and a hall-sensor
network. Nothing in the placement flow knows a footprint contains vias, and
`score_placement` will not tell you: it reasons about courtyards, and a via is
not a courtyard.

During placement review:

```bash
grep -l "ThermalVias" hw/*.kicad_pcb hw/**/*.kicad_mod
```

For every footprint whose name contains `ThermalVias` (or that has pads of
type `SMD` with a drill, or any `pad` on `*.Cu`), **look at what is directly
opposite it on the other side**. Either move the opposite-side parts clear,
strip the vias from the variant and place your own, or use the plain variant.

This one reaches fabrication if you do not check it.

## 4. Derive keep-outs from footprints, never from a remembered number

A keep-out written as `RING_R = 6.60` while the footprint it is guarding
(`MOTOR_TERM_RING_8_D17mm`) places its pads at 8.50 mm protects bare laminate
and leaves the actual pads exposed — and parts get placed on four of them.
DRC finds it; inspection does not, because the number looks plausible.

Read the dimension out of the footprint:

```python
fp = board.FindFootprintByReference("J5")
r = max((pad.GetPosition() - fp.GetPosition()).EuclideanNorm()
        for pad in fp.Pads())
keepout_r = pcbnew.ToMM(r) + clearance_mm
```

Wherever a constant in a layout script mirrors a footprint dimension, it will
drift the first time the footprint changes, and nothing will say so. Read it.

## 5. Konnect quirks worth knowing before they cost time

* **`score_placement` uses bounding boxes.** An annular footprint — a motor
  terminal ring, a connector shell with a central cutout — reports its bbox as
  solid, so anything inside the ring comes back as a `hard_fail` courtyard
  overlap. On one board that was four 24 mm² "overlaps" where the real copper
  clearance was 1.45 mm. Check the courtyard polygon yourself before believing
  a hard failure on an annular or L-shaped part; the verdict does not change
  on a re-run, so re-running is not a test.
* **`set_footprint_graphics` validates one field per call.** Expect a chain of
  rejections — `footprint_path`, `selector`, `mode`, `selector.layer`,
  `graphics`, `radius_mm`, `stroke_width_mm`, `fill` — and note that `fill`
  takes `"none"`, not `false`. Build the whole argument set from the first
  error rather than fixing one field at a time.

---

## 6. Autorouting with freerouting

Two defects in freerouting 2.1.0 and one in KiCad's DSN export make this
process fail in ways that look like board problems.

### 6a. KiCad's DSN export writes fractional coordinates into an integer file

The header declares `(resolution um 10)` — integer tenths of a micron — and
then arc tessellation in the board outline emits values like `78497.5`.
freerouting does not report a parse error. It reports *"the maze search
algorithm could not be created"* for **every** connection and routes nothing,
which reads exactly like an outline or a keepout problem.

**Always round-trip the DSN before using it:**

```bash
kicad-cli pcb export specctra hw/probe.kicad_pcb --output build/probe.dsn

python3 - <<'PY'
import re
src = "build/probe.dsn"
text = open(src).read()
# The resolution line says the file is integers. Make that true.
fixed, n = re.subn(r"(?<![\w.])(-?\d+)\.\d+(?![\w.])",
                   lambda m: m.group(1), text)
open(src, "w").write(fixed)
print(f"integerised {n} coordinate(s)")
PY
```

If that prints a non-zero count, the file you were about to route was
invalid. Check the count every time: it is the cheapest possible test and it
saves an hour of testing the board instead of the file.

### 6b. freerouting ignores every stop condition, and only writes on a clean exit

None of these bind: `-mp 60` (ran to pass 79), `router.max_passes` in
`freerouting.json`, `optimizer.max_passes: 0`, `job_timeout: 00:20:00` (a run
asked for 30 passes was at pass 67 after 22 minutes).

That would merely be annoying, except the session file is **written only when
the job ends cleanly**. An unbounded run that you kill produces **nothing at
all** — a route that had reached 75 unrouted of 234 was lost three separate
times this way.

**Drive it through its API server instead**, where the job result can be
fetched without waiting for the process to exit:

```bash
java -jar freerouting.jar --gui=false --api_server=true --port=37864 &
# POST the session, poll the job, GET the output when the pass count or the
# unrouted count stops improving — and keep every intermediate result.
```

If you must use the CLI, treat every run as disposable and snapshot whatever
it has produced before it can be lost. A partial route you still have beats a
better one you do not.

### 6c. Do not blame the board first

The order to check, when freerouting routes nothing:

1. The DSN round trip above — is the file actually integers?
2. Net class widths against pad sizes (§1) — can a track physically enter?
3. Net class clearances against pad pitch (§1) — is the class self-violating?
4. DRC on the placed board (§2) — is the placement legal at all?
5. Only then: the outline, the keepouts, the layer types.

That order is the reverse of the order they get investigated in, and the first
three cost about a minute each.
