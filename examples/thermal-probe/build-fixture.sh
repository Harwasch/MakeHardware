#!/usr/bin/env bash
# Rebuild the Thermal Probe example project from scratch.
#
# The example exists so the review artifact can be developed against realistic
# input: a project part-way through, with one milestone approved, one awaiting
# an answer, one gone stale, and one not yet requested. Every artefact below is
# produced by the real MakeHardware tools except the vision renders and the
# requirements export, which need build123d and strictdoc; build-fixture.py
# writes those in the shape the real tools emit.
#
#   ./build-fixture.sh
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

S="$(cd ../../plugins/makehardware/scripts && pwd)"
PY="${HARDWARE_PYTHON:-python3}"
plan()   { "${PY}" "${S}/plan_render.py" "$@"; }
block()  { "${PY}" "${S}/block_diagram.py" "$@"; }
review() { "${PY}" "${S}/review_gate.py" "$@"; }

echo "== 1. vision renders and requirements export =="
"${PY}" build-fixture.py || exit 1

echo
echo "== 2. design-stage artefacts (CAD, schematic, plots) =="
"${PY}" build-design-fixtures.py || exit 1

echo
echo "== 2b. schematic sheets, from the real exporter =="
# The schematic tab carries genuine kicad-cli output rather than a drawing of
# some, because what the exporter emits is nothing like what you would write by
# hand: page size in millimetres, one <path> per line segment, a hardcoded
# light sheet, and layer-named ids that collide between sheets. Those are the
# hazards the review page has to survive, so the fixture should contain them.
#
# The committed SVGs are the record; this step only refreshes them where the
# tool is available. KiCad's own pic_programmer demo stands in for a schematic
# this container has no way to draw.
if command -v kicad-cli >/dev/null 2>&1 && [ -f hw/kicad-demo/pic_programmer.kicad_sch ]; then
    tmp=$(mktemp -d)
    if kicad-cli sch export svg hw/kicad-demo/pic_programmer.kicad_sch \
            --output "${tmp}" >/dev/null 2>&1; then
        cp "${tmp}/pic_programmer.svg"              docs/design/schematic/sheet-1-main.svg
        cp "${tmp}/pic_programmer-pic_sockets.svg"  docs/design/schematic/sheet-2-sockets.svg
        echo "  re-exported 2 sheets with $(kicad-cli version 2>/dev/null || echo kicad-cli)"
    else
        echo "  kicad-cli export failed — keeping the committed sheets"
    fi
    rm -rf "${tmp}"
else
    echo "  no kicad-cli — keeping the committed sheets"
fi

echo
echo "== 3. block diagram and power budget =="
# --relayout, or the previous run's hand-placed positions are read back and
# the layout under test never changes.
block --relayout >/dev/null 2>&1
block --summary 2>/dev/null | head -8

echo
echo "== 4. plan chart and scope document =="
# The plan gate refuses a `done` chunk whose review is unsigned, and the plan
# review needs docs/plan.md to exist — so render once with the claims relaxed,
# exactly as a real project does before its first review, then restore.
cp plan.yaml .plan.yaml.bak
"${PY}" - <<'PYEOF'
import yaml
p = yaml.safe_load(open("plan.yaml"))
for c in p["chunks"]:
    if c.get("status") == "done":
        c["status"] = "in_progress"
yaml.safe_dump(p, open("plan.yaml", "w"), sort_keys=False, allow_unicode=True)
PYEOF
plan >/dev/null 2>&1
mv .plan.yaml.bak plan.yaml

echo
echo "== 5. the review ledger =="
rm -f docs/review/reviews.yaml

# Approved, and still valid.
review open vision \
    --title "Vision and concept selection" \
    --summary "Two concepts that differ in a nameable way: a one-handed wand
with the probe on a lead, and a bench instrument that lives on a shelf. Both
envelopes are measured off real geometry." \
    --artifact docs/design/vision.md --artifact docs/design/vision/ \
    --reference concepts/ \
    --question "Which concept, and what made you pick it?" \
    --question "Is 164 mm too long to hold comfortably in a glove?" >/dev/null
review sign vision --approve --by harrison \
    --note "The wand. A freezer walk is one-handed and you are already carrying
a clipboard — the bench version solves a problem we do not have." >/dev/null

# Approved, and still valid.
review open plan \
    --title "Project plan" \
    --summary "Eleven chunks, nine sessions on the critical path. Layout is
blocked on the enclosure envelope, which is the dependency I am least sure
about." \
    --artifact docs/plan.md \
    --reference docs/plan.svg --reference docs/plan.drawio --reference plan.yaml \
    --question "Is this all the work?" \
    --question "Is the order right — do you know a lead time we do not?" >/dev/null
review sign plan --approve --by harrison \
    --note "Add the drop test earlier if the enclosure is printed rather than
moulded. Otherwise the order is right." >/dev/null

# Approved, then an artefact moved underneath it — the case the ledger exists
# to catch.
review open requirements \
    --title "Requirements tree" \
    --summary "Fifteen requirements. SYS-001 moved from 12 h to 7 d after the
logging interval was settled at one minute, which is the number worth arguing
about." \
    --artifact docs/design/requirements-map.svg \
    --reference requirements/ \
    --question "Is 7 days the right target, or is 5 with a smaller cell better?" \
    --question "Is anything here that nobody asked for?" >/dev/null
review sign requirements --approve --by harrison \
    --note "7 days. A week means Friday-to-Friday and nobody has to think." >/dev/null
# ELE-003 was added after sign-off, so the map is no longer what was agreed.
"${PY}" - <<'PYEOF'
import re
p = "docs/design/requirements-map.svg"
s = open(p).read()
open(p, "w").write(s.replace("ADC error &lt;= 0.2 degC", "ADC error &lt;= 0.15 degC"))
PYEOF

# Requested, waiting on an answer — the one currently in front of the human.
review open architecture \
    --title "Block diagram, power tree and buses" \
    --summary "Four rails. VBUS is the tight one at 90% of the USB-C default
500 mA while charging, which is fine because it is a charge-only rail — but it
is the number to check. Standby on V3P3 comes to 12 uA of the 40 uA budget." \
    --artifact docs/design/block-diagram.svg \
    --reference hw/block-diagram.yaml --reference hw/block-diagram.drawio \
    --question "Is a rail or a part missing?" \
    --question "SPI1 shares flash and LCD on one bus — acceptable, or separate them?" \
    --question "Is charging at 450 mA off a 500 mA port too close?" >/dev/null

# Approved, and still valid — a design stage, not one of the four milestones.
review open cad --title "Enclosure, rev C" \
    --summary "Envelope frozen from the agreed wand concept. The board outline is
published as an interface at 33.4 x 96 mm and the electrical side is now working
to it, so moving it is expensive from here." \
    --artifact docs/design/cad/enclosure-render.png \
    --artifact docs/design/cad/enclosure-section.svg \
    --reference cad/enclosure.py \
    --question "Board-to-lid clearance is 8.4 mm. Enough for the display and its zebra strip?" \
    --question "Split line at 40% depth puts the seam on the grip. Acceptable?" >/dev/null
review sign cad --approve --by harrison \
    --note "Yes to both. Move the seam to 45% if the tooling allows it, but do not
hold the schematic for it." >/dev/null

echo
echo "== 6. re-render the plan, now that the reviews exist =="
plan --check && plan >/dev/null && echo "  plan renders clean"

echo
echo "== 7. the review page =="
"${PY}" "${S}/review_artifact.py"

echo
review list
