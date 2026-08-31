# Fabrication notes

What the fab needs in writing, beyond the gerbers. Everything here is quoted
against, so a change to any of it invalidates the prices in `quotes.csv`.

## Board

| Item | Value |
|---|---|
| Layers | 2 |
| Material | FR-4 TG150 |
| Finished thickness | 1.62 mm ±10% |
| Copper | 1 oz both sides |
| Finish | ENIG |
| Soldermask | Green, both sides |
| Silkscreen | White, top only |
| Outline tolerance | ±0.15 mm |
| Min track / gap | 0.15 mm |
| Min drill, finished | 0.30 mm |
| Min annular ring | 0.13 mm |
| Electrical test | 100% netlist |
| Acceptance | IPC-A-600 class 2 |

## Panelisation

Ship as singles at 25 off. At 100 off, a 2 x 3 panel on 3 mm tab routing with
breakaway rails — the assembler's conveyor needs 3 mm of clearance on the long
edges and the current outline does not leave it.

## Things a fab has queried before

* **ENIG at 25 off.** Two of the three quotes carry a surcharge below 50
  pieces. It is priced in above; if the run grows to 50 the unit cost drops
  more than the quantity alone suggests.
* **The 1.00 mm test point** is the smallest hole on the board and the only
  one not on the M3 pattern. It is deliberate and it is plated.
* **No impedance control is specified.** Nothing on this board is a
  transmission line at the speeds involved, and asking for it adds a coupon
  and about 30% to the fab cost.
