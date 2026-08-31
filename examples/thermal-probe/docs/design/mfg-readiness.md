# Manufacturing readiness

Assessed 2026-08-29 against a first article run of 25 units.
**Not ready to release.** Two gates are open and one is blocked on a quote.

| Gate | State | Evidence | What is missing |
|---|---|---|---|
| Schematic frozen | Not ready | ERC clean, 2 no-connects flagged | Schematic review not signed off |
| Layout frozen | Not started | — | Blocked on E2 |
| DRC clean on the current board | Not started | — | Blocked on E3 |
| Fabrication outputs generated | Not started | — | Blocked on E3 |
| Stackup agreed with the fab | Ready | `docs/design/stackup.svg` | Confirm ENIG availability at 25 off |
| BOM fully quoted | Not ready | `docs/design/bom-summary.csv` | 3 of 14 lines are estimates |
| Every part second-sourced | Not ready | — | U3 and DS1 are single-source |
| Assembly drawing | Not started | — | Needs the layout |
| Test fixture defined | Not started | — | Needs the layout |
| Enclosure process chosen | Not ready | — | Print vs mould decision at 100+ |

The two that matter for the decision in front of you: **DS1 has no distributor
stock at any quantity**, which makes the display a single-source part on a
factory lead time, and the **enclosure cost swings 3x** between printing and
tooling at the volumes under discussion.
