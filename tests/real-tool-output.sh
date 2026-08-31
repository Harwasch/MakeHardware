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
#   1. kicad-cli writes page size in MILLIMETRES (`width="297mm"`). Reading the
#      number and dropping the unit renders an A4 schematic 297 px wide.
#   2. kicad-cli and matplotlib both ship a <style> block. Inlined, its
#      selectors are global: their `.t` restyles this page, and this page's
#      restyles theirs. Both directions have to be scoped away.
#   3. Exporters emit ids (`#glyph0-1`, gradients, markers). Two files on one
#      page collide and the last definition wins for both.
#   4. A build123d or pcbnew render is megabytes. It must not be embedded, and
#      must not vanish either.
#   5. A PDF is the normal schematic export and cannot be inlined at all.
#   6. An export that failed leaves no file. That must be reported, loudly.
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

# ---- 1-3: an SVG shaped like kicad-cli's, twice, with colliding names -----
for n in 1 2; do
cat > "docs/design/sheet-${n}.svg" <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="297mm" height="210mm" viewBox="0 0 1122.5 793.7" version="1.1">
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
<rect width="1122.5" height="793.7" fill="#ffffff"/>
<use xlink:href="#glyph0-1" x="40" y="40"/>
<line x1="60" y1="60" x2="300" y2="60" marker-end="url(#arrow)" stroke="#000"/>
<text class="t" x="60" y="120">SHEET ${n} MARKER</text>
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

# 1. millimetres
if grep -qE 'max-width:1[01][0-9][0-9]px' "${P}"; then
    pass "297mm page read as ~1122 px, not 297"
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

# scripts must not survive into the page
grep -q "exporters should not ship this" "${P}" \
    && fail "a <script> from the SVG was inlined" \
    || pass "script stripped from the inlined SVG"

# 4/5/6. unusable artefacts are reported, never dropped
for want in "board-render.png" "schematic.pdf" "never-exported.svg"; do
    has "${P}" "${want}" && pass "reported on the page: ${want}" \
                         || fail "silently dropped: ${want}"
done
has "${P}" "Open on GitHub" && pass "the PDF links out to where it does render" \
    || fail "no GitHub link offered for the PDF"

sz=$(( $(wc -c < "${P}") / 1024 ))
[ "${sz}" -lt 500 ] && pass "page stayed small (${sz} kB) — the 1.5 MB raster was not embedded" \
                    || fail "page ballooned to ${sz} kB"

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
