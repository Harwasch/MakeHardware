#!/usr/bin/env bash
# Does review-artifact survive what the real tools actually emit?
#
# The example project is built in a container that has no KiCad, no build123d
# and no strictdoc, so its fixtures are tidy SVGs written by us. Real output is
# not tidy, and every hazard below has a specific way of breaking the page
# *silently* — which is the dangerous kind, because the agent publishes a page
# with a hole in it and nobody knows until the human is confused.
#
# So this builds inputs with the hazards deliberately present and asserts the
# generator handles each one:
#
# Several of these were guesses until kicad-cli was installed and pointed at
# KiCad's own demo projects. The corrected shapes are what 7.0.11 emits and
# what the 10.0 source (common/plotters/SVG_plotter.cpp) still emits:
#
#   1. Page size is in MILLIMETRES, in BOTH places and meaning different
#      things: `width="297.0022mm"` is the intrinsic size, while
#      `viewBox="0 0 297.0022 210.0072"` is the user-unit system. Preferring
#      the viewBox — which this did — laid an A4 schematic out 297 px wide.
#   2. matplotlib ships a <style> block. Inlined, its selectors are global:
#      its `.t` restyles this page and this page's restyles it. Both
#      directions have to be scoped away. (KiCad ships none: it writes inline
#      `style="fill:#840000"` on every <g> instead, which no scoping can
#      reach — see 7.)
#   3. Exporters emit ids. KiCad 7 emitted none, but KiCad 10 names every
#      layer group — `<g id="Wire">`, `id="Notes">` — so two sheets on one
#      page collide on ids that are near-certain to repeat. matplotlib and
#      cairo emit `#glyph0-1`, gradients and markers.
#   4. A build123d or pcbnew render is megabytes. It must not be embedded, and
#      must not vanish either.
#   5. A PDF is the normal schematic export and cannot be inlined at all.
#   6. An export that failed leaves no file. That must be reported, loudly.
#   7. KiCad paints a full-page `fill:#F5F4EF` rect and draws in black, all
#      inline. On a dark page that is either a blinding slab or invisible ink,
#      and recolouring it would misrepresent the artefact — so it is matted.
#  10. A 3D model has to travel *inside* the page. The artifact CSP blocks a
#      fetch of a separate file, so a `.glb` referenced by path is a viewer
#      nobody sees — and an inlined one has to have a budget of its own, or a
#      manufacturing-tolerance export walks the page into the 16 MB cap.
#   8. A plotted sheet is HUGE. KiCad writes one <path> per line segment,
#      including every stroke of every character: 3.0 MB / 61,681 elements for
#      one A4 sheet of the pic_programmer demo. Inlining without a budget
#      walks the page into the 16 MB artifact cap.
#
#   tests/real-tool-output.sh
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
S="${ROOT}/plugins/makehardware/scripts"
PY="${HARDWARE_PYTHON:-python3}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/mh-realtool.XXXXXX")
trap 'rm -rf "${WORK}"' EXIT

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }
has()  { grep -qF "$2" "$1"; }

cd "${WORK}"
mkdir -p docs/design docs/review
git init -q .
git remote add origin https://github.com/Harwasch/realtool-test.git
cat > plan.yaml <<'EOF'
project: Real Tool Test
chunks:
  - {id: E1, title: Capture, discipline: electrical, status: todo,
     depends_on: [], estimate_sessions: 1, outputs: []}
EOF

# ---- 1-3: two exporter-shaped SVGs on one page, with colliding names ------
# Note the viewBox: KiCad's is in the SAME units as the width, so a generator
# that trusts the viewBox gets 297 instead of 1122. The fixture used to write
# a px-shaped viewBox here, which is why that bug survived the test suite.
for n in 1 2; do
cat > "docs/design/sheet-${n}.svg" <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
 <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns:svg="http://www.w3.org/2000/svg" xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="297.0022mm" height="210.0072mm"
     viewBox="0.0000 0.0000 297.0022 210.0072" version="1.1">
<style>
  .t { fill: #ff00ff; font-size: 40px }
  .h { fill: #ff00ff }
  text { fill: #000000 }
  @media (prefers-color-scheme: dark) { .t { fill: #00ff00 } text { fill: #ffffff } }
</style>
<defs>
  <marker id="arrow" markerWidth="6" markerHeight="6"><path d="M0,0 L6,3 L0,6 z"/></marker>
  <g id="glyph0-1"><path d="M2,2 L8,8"/></g>
</defs>
<script>window.alert('exporters should not ship this, but some do')</script>
<g style="fill:#F5F4EF; fill-opacity:1.0000; stroke:#F5F4EF;">
<rect x="0.000000" y="0.000000" width="297.002200" height="210.007200" rx="0.000000" />
</g>
<g id="Wire" inkscape:label="Wire" inkscape:groupmode="layer">
<use xlink:href="#glyph0-1" x="40" y="40"/>
<line x1="60" y1="60" x2="300" y2="60" marker-end="url(#arrow)" stroke="#000"/>
</g>
<g id="Notes" inkscape:label="Notes" inkscape:groupmode="layer">
<text class="t" x="60" y="120">SHEET ${n} MARKER</text>
</g>
</svg>
EOF
done

# ---- 4: an oversized raster, as build123d/pcbnew produce -----------------
"${PY}" - <<'PYEOF'
import struct, zlib
w = h = 900                        # ~1.5 MB of incompressible noise
rnd, rows = 12345, []
for y in range(h):
    px = bytearray([0])
    for x in range(w * 3):
        rnd = (1103515245 * rnd + 12345) & 0x7FFFFFFF
        px.append(rnd >> 16 & 0xFF)
    rows.append(bytes(px))
raw = zlib.compress(b"".join(rows), 0)
def chunk(t, d):
    c = t + d
    return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
open("docs/design/board-render.png", "wb").write(png)
print(f"  (built a {len(png)//1024} kB render)")
PYEOF

# ---- 8: a plotted sheet at real KiCad density ----------------------------
# One <path> per line segment is what the plotter actually does, so this is
# not an exaggerated fixture: it is 40k two-point paths, which a real A4 sheet
# comfortably exceeds.
"${PY}" - <<'PYEOF2'
seg = ['<path d="M%.4f %.4f\nL%.4f %.4f\n" />'
       % (i % 297, i % 210, (i + 1) % 297, (i + 3) % 210) for i in range(40000)]
open("docs/design/dense-sheet.svg", "w").write(
    '<?xml version="1.0" standalone="no"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="297.0022mm" '
    'height="210.0072mm" viewBox="0.0000 0.0000 297.0022 210.0072">'
    '<g style="fill:#000000; stroke:#000000;">' + "".join(seg) + '</g></svg>')
PYEOF2
printf '  (built a %s kB dense sheet)\n' "$(( $(wc -c < docs/design/dense-sheet.svg) / 1024 ))"

# ---- 9: a diagram whose editable source lives in another directory -------
# `block-diagram` writes hw/block-diagram.drawio and docs/design/block-diagram.svg,
# so a same-directory lookup finds the plan and the requirements map and misses
# the block diagram — the one people most want to open, because it is the one
# they argue with. A missing link is invisible on the page, so assert it.
mkdir -p hw
cat > docs/design/block-diagram.svg <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"
     viewBox="0 0 600 300"><rect width="600" height="300" fill="none"/>
<text x="20" y="40">BLOCK DIAGRAM</text></svg>
EOF
cat > hw/block-diagram.drawio <<'EOF'
<mxfile host="MakeHardware"><diagram id="d" name="Page-1"><mxGraphModel>
<root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>
EOF

# ---- 5: a PDF, the normal schematic export -------------------------------
printf '%%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n' \
    > docs/design/schematic.pdf

cat > docs/review/artifact.yaml <<'EOF'
title: Real Tool Test
phases:
  - id: schematic
    title: Schematic
    always: true
    images:
      - docs/design/sheet-1.svg
      - docs/design/sheet-2.svg
      - docs/design/schematic.pdf
      - docs/design/board-render.png
      - docs/design/never-exported.svg
      - docs/design/dense-sheet.svg
      - docs/design/block-diagram.svg
EOF

git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm fixtures >/dev/null 2>&1

echo "Real tool output"
echo

echo "preflight"
out=$("${PY}" "${S}/review_artifact.py" --check 2>&1); rc=$?
[ ${rc} -eq 1 ] && pass "--check exits 1 when artefacts cannot be shown" \
                || fail "--check should have exited 1, got ${rc}"
[[ ${out} == *"never-exported.svg"* ]] && pass "--check names the missing export" \
    || fail "--check did not name the missing export"

echo
echo "page"
"${PY}" "${S}/review_artifact.py" >/dev/null 2>&1
P=docs/review/artifact.html
[ -s "${P}" ] && pass "page written despite unusable artefacts" \
              || { fail "no page written"; echo "${fails} failure(s)"; exit 1; }

# 1. millimetres, from the width attribute rather than the viewBox
if grep -qE 'max-width:1[01][0-9][0-9]px' "${P}"; then
    pass "297.0022mm page read as ~1122 px, not 297"
else
    fail "mm units mis-parsed: $(grep -oE 'max-width:[0-9]+px' "${P}" | head -2 | tr '\n' ' ')"
fi

# 2. style scoping, both directions
if grep -qE '#g[0-9a-f]{7} \.t\{' "${P}"; then
    pass "the exporter's own CSS is scoped to its wrapper"
else
    fail "exporter CSS left global — it will restyle the page"
fi
has "${P}" 'fill: #ff00ff' && pass "scoped rules keep their declarations" \
    || fail "declarations lost while scoping"

# The @media block is where scoping went wrong before: its first rule kept the
# `@media (...)` in its prelude, so it was left global while the rules after it
# were scoped and the braces stopped balancing. That leaked the exporter's dark
# palette onto the whole page.
if grep -qE '@media \(prefers-color-scheme:dark\)\{:root:not' "${P}"; then
    pass "dark-mode rules are scoped and guarded"
else
    fail "@media block not scoped — it will leak onto the page"
fi
grep -q ':root\[data-theme="dark"\] #g' "${P}" \
    && pass "an explicit dark toggle reaches the inlined SVG" \
    || fail "inlined SVG only follows the OS, not the page's theme choice"
"${PY}" - "${P}" <<'PYEOF'
import re, sys
css = "".join(re.findall(r"<style>(.*?)</style>", open(sys.argv[1]).read(), re.S))
assert css.count("{") == css.count("}"), "unbalanced braces in the page CSS"
print("  [32mPASS[0m  page CSS braces balance")
PYEOF
[ $? -eq 0 ] || fails=$((fails+1))

# 3. id collisions between the two sheets
ids=$(grep -oE 'id="g[0-9a-f]{7}-arrow"' "${P}" | sort -u | wc -l)
[ "${ids}" -eq 2 ] && pass "the two sheets' ids namespaced apart (${ids} distinct)" \
                   || fail "id collision: ${ids} distinct #arrow ids, expected 2"
has "${P}" 'xlink:href="#g' && pass "xlink:href rewritten to the namespaced id" \
    || fail "xlink:href left pointing at the un-namespaced id"

# KiCad 10 names its layer groups, so `id="Wire"` appears in every sheet of
# every project. Two sheets on one page is the common case, not the corner one.
wires=$(grep -oE 'id="g[0-9a-f]{7}-Wire"' "${P}" | sort -u | wc -l)
[ "${wires}" -eq 2 ] \
    && pass "KiCad 10 layer ids namespaced apart (${wires} distinct #Wire)" \
    || fail "KiCad 10 layer id collision: ${wires} distinct #Wire, expected 2"

# 7. the light sheet is matted rather than left to glare or recoloured
mats=$(grep -c 'class="sheet mat"' "${P}")
[ "${mats}" -ge 2 ] && pass "light-background sheets matted (${mats})" \
    || fail "a #F5F4EF full-page sheet was not matted (${mats} matted)"

# scripts must not survive into the page
grep -q "exporters should not ship this" "${P}" \
    && fail "a <script> from the SVG was inlined" \
    || pass "script stripped from the inlined SVG"

# 4/5/6. unusable artefacts are reported, never dropped
for want in "board-render.png" "schematic.pdf" "never-exported.svg" \
            "dense-sheet.svg"; do
    has "${P}" "${want}" && pass "reported on the page: ${want}" \
                         || fail "silently dropped: ${want}"
done
has "${P}" "Open on GitHub" && pass "the PDF links out to where it does render" \
    || fail "no GitHub link offered for the PDF"

# 8. the dense sheet must be reported, not pasted in
grep -q 'M0.0000 0.0000' "${P}" \
    && fail "a 40,000-element sheet was inlined — the page will crawl" \
    || pass "dense plotted sheet reported, not inlined"

# 9. the editable original is offered at the picture, across directories
has "${P}" "app.diagrams.net/?url=" \
    && pass "a .drawio opens straight in draw.io from its raw URL" \
    || fail "no draw.io link — the diagram is read-only on the page"
has "${P}" "hw%2Fblock-diagram.drawio" \
    && pass "found the .drawio in hw/ for an SVG in docs/design/" \
    || fail "cross-directory .drawio not found: the block diagram is the case"

sz=$(( $(wc -c < "${P}") / 1024 ))
[ "${sz}" -lt 500 ] && pass "page stayed small (${sz} kB) — neither the 1.5 MB raster nor the dense sheet was embedded" \
                    || fail "page ballooned to ${sz} kB"


# ---------------------------------------------------------------------------
# 10-12: the interactive half of the page.
#
# Pan/zoom, the 3D viewer and sortable tables are the reason to publish the
# page at all — a plotted A4 sheet squeezed into a browser column is legible
# as a shape and unreadable as a document. All three are inert markup until
# the JS runs, so what is asserted here is that the markup and the script are
# both present and that the model went in as a data URI: the artifact CSP
# blocks fetching a separate file, so a model referenced by path is a model
# nobody sees.
# ---------------------------------------------------------------------------
echo
echo "== the interactive half =="

has "${P}" 'class="zoom"' \
    && pass "figures are wrapped for pan and zoom" \
    || fail "no .zoom wrapper — every sheet is a fixed-size picture again"
has "${P}" "data-z=\"fit\"" \
    && pass "the zoom controls are on the page" \
    || fail "no zoom controls"
has "${P}" "scroll to zoom" \
    && pass "…and they say what they do" \
    || fail "the affordance is invisible"
has "${P}" "cdn.jsdelivr.net/npm/three@" \
    && pass "the 3D viewer's library is pinned to an exact version" \
    || fail "three.js is not loaded, or not pinned"
# A .glb becomes a viewer with the model inlined; an oversized one is reported
# rather than dropped, the same way an oversized SVG is.
mkdir -p docs/design/cad
"${PY}" - <<'MKGLB'
import base64, json, struct
# The smallest valid GLB: an empty glTF asset. Enough to prove the pipeline
# inlines it; the real one is exercised by the example project.
doc = json.dumps({"asset": {"version": "2.0"}, "scenes": [{"nodes": []}],
                  "scene": 0}).encode()
doc += b" " * ((4 - len(doc) % 4) % 4)
glb = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(doc))
       + struct.pack("<II", len(doc), 0x4E4F534A) + doc)
open("docs/design/cad/tiny.glb", "wb").write(glb)
open("docs/design/cad/huge.glb", "wb").write(glb + b"\0" * (3 * 1024 * 1024))
MKGLB

printf 'Ref,Part,Qty,@1k\nR1,10k 1%%,4,0.01\nU1,MCU,1,1.82\n' \
    > docs/design/bom.csv

cat > docs/review/artifact.yaml <<'EOF'
title: Real Tool Test
phases:
  - id: cad
    title: CAD
    always: true
    images:
      - docs/design/cad/tiny.glb
      - docs/design/cad/huge.glb
    tables:
      - csv: docs/design/bom.csv
        title: BOM
EOF
git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm glb >/dev/null 2>&1
"${PY}" "${S}/review_artifact.py" >/dev/null 2>&1

has "${P}" 'data-model="data:model/gltf-binary;base64,' \
    && pass "a .glb is inlined as a data URI, which the CSP requires" \
    || fail "the model is not inlined — the viewer would fetch and be blocked"
has "${P}" "over the 2500 kB model budget" \
    && pass "an oversized model is reported, not silently dropped" \
    || fail "the oversized .glb vanished"
has "${P}" "coarser tolerance" \
    && pass "…and the report names the fix" \
    || fail "the model budget message does not say what to do"
has "${P}" 'table class="sortable"' \
    && pass "a CSV table is sortable" || fail "tables are inert"
has "${P}" 'th class="sortable"' \
    && pass "…and every heading is the control" || fail "headings are not clickable"

sz=$(( $(wc -c < "${P}") / 1024 ))
[ "${sz}" -lt 900 ] \
    && pass "page stayed small (${sz} kB) with the 3 MB model refused" \
    || fail "page ballooned to ${sz} kB — the model budget did not hold"

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
