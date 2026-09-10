# Electrical design

| File | What it is |
|---|---|
| `block-diagram.yaml` | the architecture spec — **the only file here you hand-edit** |
| `block-diagram.drawio` | generated; open in draw.io to rearrange, positions are kept |
| `*.kicad_sch`, `*.kicad_pcb` | KiCad project — change these through KiStack (live IPC, or the file with a re-render after), never with `sed` |

The block diagram is settled before schematic capture. See the
`hw-block-diagram` skill; run `block-diagram --check` before calling the
architecture agreed.
