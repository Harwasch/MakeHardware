# House KiCad templates

Copied into a project by `/hw-new-project`. Two files, and one trap.

## `makehardware.kicad_wks` — the drawing sheet

A3 frame, zone rulers, and a title block at the bottom right carrying the
company, the project title, the sheet name and hierarchical path, the source
filename, the date, the revision and *sheet n of m*. Every field is a KiCad
text variable, so nothing in this file is ever edited per project: set Title,
Revision, Date and Company in Page Settings and they appear here.

The last line of the frame says the drawing is generated and points at the
source. That is not decoration — a reader who thinks a drawing was drawn by
hand will edit the drawing, and the edit will be gone on the next render.

Install it:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/templates/kicad/makehardware.kicad_wks" hw/
kicad-cli sch export pdf hw/probe.kicad_sch \
    --drawing-sheet hw/makehardware.kicad_wks --output build/check.pdf
```

Then point the project at it permanently, either in Page Settings or as
`schematic.page_layout_descr_file` in the `.kicad_pro`.

**The trap: a bad drawing sheet fails silently.** KiCad's page-layout parser is
not the same parser as the rest of the S-expression files — it rejects `;;`
comments, and on any parse error `kicad-cli` prints one line to stderr,
**still exits 0**, and plots with the built-in sheet instead. So a broken
template produces a perfectly good-looking PDF with the wrong frame on it. That
is why this file carries no comments, and why the check above is worth running
once after any edit:

```bash
grep -c MakeHardware build/check.pdf     # 0 means the template did not load
```

## `konnect-house.json` — grid, sizes and net classes

Loaded through Konnect's `save_project_config`. Every number in it is one that
`sch-lint` or `pcb-lint` checks, so if you change one here, change the gate's
default with it — a house standard and a gate that disagree is worse than
neither.

The net-class widths deserve their own note. They are set to values a router
can physically enter a pad with, not to final current-carrying widths. A
`Power` class at 1.20 mm against a 0.25 mm QFN pad is not an error and not a
DRC violation; it is simply unroutable, and it presents as a router returning
almost every connection as a failure with no explanation. Route at the widths
here, then widen the power nets and re-run DRC. `final_track_width_mm` records
what the widening has to reach. See
`hw-verification/references/pcb-layout.md` §1.
