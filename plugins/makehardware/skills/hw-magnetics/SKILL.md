---
name: hw-magnetics
description: Field simulation - inductance, coupling, eddy and proximity loss, magnetic force - with FastHenry, Elmer, GetDP and Gmsh. Use when a coil, transformer, inductor, motor, magnet or wireless-power link needs L, M, k, Q, R_ac(f), a B field or a force, when a design has ferrite or a core in it, or when a magnetics geometry needs parameterising and sweeping. Not for circuit simulation - that is hw-simulation.
---

# Magnetics and field simulation

SPICE cannot tell you an inductance. These tools can, and each answers a
different question — picking the wrong one is the main way this goes wrong.

Run `hw-doctor` if a tool is missing; the environment build reports what it
managed to install.

## Which tool

| The question | Tool | Why not the other |
|---|---|---|
| L, M, k, Q, R_ac(f) of **air-core** conductors | **FastHenry** | PEEC: no air mesh at all. Seconds, against a 200k-element FEA of the same problem. |
| Anything with **ferrite, a core, a shield, or saturation** | **Elmer** | FastHenry is conductors only, µr = 1 everywhere. It has nothing to say about a core. |
| Frequency-domain eddy and proximity loss | **Elmer** harmonic | complex-valued A-v edge elements |
| 3-D magnetostatics, permanent-magnet machines | **Elmer** | PM and circuit support |
| Fast permanent-magnet field or force screening | **magpylib** | analytic, milliseconds, no mesh |
| Structural: contact, nonlinear, modal | **CalculiX** | Abaqus `.inp`, which agents write far more reliably than `.sif` |
| Meshing, for any of the above | **Gmsh** | Elmer has no geometry kernel and no mesher |
| **Core loss** | Python, iGSE/Steinmetz against the FEA B field | never a solver output; the coefficients are a datasheet number |

If the answer is FastHenry, take it. A ferrite-free coil problem that lands in
an FEA is an afternoon that should have been a minute.

## The shape of a study

A parametric study is **a Python driver that generates input, shells out to
the solver, parses the result and plots** — never a hand-edited input file.
That is what makes this stack agent-drivable and what lets a geometry fix
re-run an entire sweep. One module owns the geometry; the deck writer, the
mesher and the drawing all call it, so they cannot disagree about the part.

Refine until the answer stops moving, and record where that was. Two
discretisations usually converge from opposite directions — a mesh from below
and a filament count from above — so a single setting proves nothing.

## Cross-check before believing

Every result gets an independent check. Not another solver: a closed form.

| Case | Reference |
|---|---|
| Mutual inductance of coaxial loops | Maxwell's elliptic-integral formula |
| Planar spiral self-inductance | Mohan's current-sheet fit (±8 %) |
| DC resistance | ρL/A on the same geometry |
| Round-wire AC resistance | the Bessel-function ratio |
| Anything Elmer, air-core | FastHenry on identical geometry |

Solver defects here are **silent**. In the WPT coil demo, two of six were
caught by a cross-check disagreeing and none by an error message.

## FastHenry

```
.units mm
.default sigma=5.8e4          <- PER MILLIMETRE, because .units is mm
N1 x=.. y=.. z=..
E1 N1 N2 w=5 h=0.035 nwinc=8 nhinc=1 rw=2
.external N1 Nlast portname
.freq fmin=1.5 fmax=150e3 ndec=1
.end
```

Run it as `fasthenry -o4 deck.inp`.

* **`-o4` is not optional.** The multipole expansion defaults to order 2,
  which is 0.40 % low on a mutual inductance that has a closed-form answer.
  That error lands directly on k. Order 4 gives 0.016 %.
* **`sigma` is per `.units`.** `.units mm` means S/mm — 5.8e4 for copper, not
  5.8e7. Get it wrong and every resistance is 1000× too small while every
  inductance looks perfect.
* **`nwinc=1` returns R_ac exactly equal to R_dc**, with no warning. One
  filament cannot represent current crowding. If a trace is wide against the
  skin depth, converge `nwinc` or your Q is fiction. `nhinc` matters only when
  the conductor is thick against the skin depth — for 35 µm foil below a
  megahertz it is not.
* **`ndec` is points per decade.** `fmin=1 fmax=150e3 ndec=100` is 518 solves.
* **FastHenry can write `nan` and exit 0.** No error, a normal timing summary,
  a successful shell. The only symptom is `nan +nanj` in `Zc.mat`. **Always
  check the parsed matrix is finite** and treat a NaN as a failure. It needs
  `nwinc > 1` and depends on the exact geometry in a way that is not monotonic
  in anything; re-discretising rescues some cases and no filament setting
  rescues others. Fall back to `nwinc=1` with the result flagged as DC-only
  rather than dropping the point silently.
* **`Zc.mat` has a fixed name** in the working directory. Give every run its
  own directory or two drivers will read each other's answers, both plausible.

## Elmer

Do **not** author a `.sif` from scratch. Copy a working one:
`/opt/elmer-elmag` carries 24 worked cases including `CoilOnIronCore` and
`CoilWithFerriteCoreAndShield`; the Elmer source tree carries ~1000
regression tests, 72 of them magnetodynamics.

* **`LD_LIBRARY_PATH=/usr/local/lib:/usr/local/lib/elmersolver`** must be set
  in every shell. The environment build puts it in `/root/.bashrc`; a
  subprocess with a scrubbed environment needs it passed explicitly.
* **`Max Output Level` below 5 suppresses the result line.** The solve still
  succeeds. `ElectroMagnetic Field Energy:` is how inductance is read out, and
  below level 5 it is simply not printed.
* **`Desired Coil Current` is NOT multiplied by `Number of Turns`.** It is
  total ampere-turns and the arithmetic is yours. Getting it wrong is a factor
  of N² on the energy — 81× for a 9-turn coil.
* **A homogenised winding is turns in parallel, not in series.** Model a
  multi-turn coil as one solid annulus and the CoilSolver finds the current
  distribution a *conductor* would take: it crowds onto the short inner path,
  where it links less flux, and the inductance comes out ~33 % low with the
  mesh and the air box both fully converged. **Mesh the turns as separate
  bodies**, one Component each, all at the same current. That brought a
  worked case to within 4 % of FastHenry.
* **A coil body present but not energised must not sit in the CoilSolver's
  equation.** `CoilSolver body 11 active in Equation but not in Component!`
  So the equation assignment depends on which solve you are doing, and the
  three solves of a mutual-inductance measurement each need their own `.sif`.
* **`Coil Normal(3)`** must be given for any winding that is not a simple
  disc. The solver's guess is wrong for a racetrack and the current then
  circulates in the wrong plane.
* The air box boundary `AV {e} = 0` is a perfect flux return — a
  superconducting enclosure. Stand it well off the coil and **converge the box
  size**, or it acts as a shorted turn.

**Inductance from energy**, which needs one scalar per solve rather than a
parsed field:

```
tx alone        W1  = ½ L₁ I²
rx alone        W2  = ½ L₂ I²
both, in phase  W12 = ½ L₁ I² + ½ L₂ I² + M I²    ->  M = W12 − W1 − W2
```

W1 and W2 must agree for a symmetric stack. That they do is the check that
both coils are wired the same way round.

**Report ferrite results as ratios** against the air-core solve on the same
mesh, and apply them to a FastHenry absolute. Homogenisation and truncation
bias is common to both and divides out of a ratio; it does not divide out of
an absolute.

## Gmsh

* Write `-format msh2` (`Mesh.MshFileVersion = 2.2`), then
  `ElmerGrid 14 2 mesh.msh -autoclean -out <dir>`. Check `<dir>/mesh.names`
  rather than assuming the mapping, and use `Use Mesh Names = True` in the
  `.sif` so bodies are matched by name.
* **`occ.fragment` renumbers every volume.** The tags returned by
  `addBox`/`fuse` are stale the instant it runs. Record each solid's centre of
  mass *before* the boolean and match parts to it afterwards; assert that
  nothing is left unclaimed.
* Build the model **in metres**. Elmer has no units, and millimetre geometry
  with SI material data is how an inductance comes out by 10³.

## Capacity

Measured on a 4-vCPU cloud session: a 200k-element Elmer magnetostatic solve
runs in ~20 s; 340k complex DOF is about the ceiling. A PCB coil with its
copper traces resolved in 3-D is ~250k tetrahedra **per coil** — over budget
and the wrong approach anyway. Homogenise the winding, or use FastHenry.

FastHenry is not the constraint: a 9-turn coil pair at 6600 filaments solves
in about 5 seconds.

## Evidence

A field result becomes evidence the same way a SPICE result does: it names the
tool and version, the geometry it came from, the convergence settings it was
taken at, and the cross-check that agreed with it. A solver number with none
of those is a guess with more decimal places.
