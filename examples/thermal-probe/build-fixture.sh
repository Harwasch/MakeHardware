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
iterate(){ "${PY}" "${S}/iterate.py" "$@"; }

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
echo "== 2c. the CAD assembly, from the real exporter =="
# cad/enclosure.py is a genuine build123d assembly — four labelled, coloured
# parts held by joints — so the STEP, GLB, STL, 3MF, joints.json, FreeCAD macro
# and every render come from cad-export rather than from a drawing of one. Only
# where build123d is installed; the committed outputs stand otherwise, the same
# rule the schematic step above follows.
if "${PY}" -c "import build123d" >/dev/null 2>&1; then
    "${PY}" "${S}/cad_export.py" cad/enclosure.py \
        --out docs/design/cad --name enclosure 2>&1 | sed -n '/wrote/,$p' | head -14
else
    echo "  no build123d — keeping the committed CAD outputs"
fi

echo
echo "== 2d. the board lint fixture =="
# No guard here: the script finds pcbnew itself, including in a different
# interpreter, and says so when it cannot.
"${PY}" build-pcb-fixture.py 2>&1 | grep -v "^\./kicad" | tail -1

echo
echo "== 2e. lint reports, drawn on the artefacts they are about =="
"${PY}" "${S}/sch_lint.py" hw/kicad-demo/pic_programmer.kicad_sch \
    --svg docs/design/lint --no-export 2>&1 | tail -3
"${PY}" "${S}/pcb_lint.py" hw/lint-fixture.kicad_pcb \
    --svg docs/design/lint/board.lint.svg 2>&1 | grep -E "^wrote|error\(s\)"

echo
echo "== 3. block diagram and power budget =="
# --relayout, or the previous run's hand-placed positions are read back and
# the layout under test never changes.
block --relayout >/dev/null 2>&1
block --summary --csv docs/design/rails.csv 2>/dev/null | head -9
"${PY}" "${S}/charts.py" budget docs/design/rails.csv \
    --out docs/design/power-budget.svg \
    --title "Rail current against budget" \
    --subtitle "Worst case per rail, from hw/block-diagram.yaml" | tail -1

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
echo "== 4b. the standby design loop =="
# The example's standby write-up ends with "the reference could be duty-cycled
# ... that is the obvious lever and it has not been modelled". This is that
# lever, modelled — and it is here because a review page that only shows where
# a design landed is the thing hw-iterate exists to replace. Note what the
# trajectory says that a final number cannot: #2 met the current target and was
# rejected on wake time, #4 was better still and rejected harder, and the pass
# that was accepted is not the best one on the objective.
rm -rf docs/design/iterations sim/standby/loop
mkdir -p sim/standby/loop
for n in 1 2 3 4 5; do
    printf 'ngspice raw (fixture stand-in) — standby loop pass %s\n' "${n}" \
        > "sim/standby/loop/pass-${n}.raw"
done

iterate open standby \
    --goal "worst in-spec standby corner under 25 uA, without making wake-up
            slower than the 10 ms the logging interval allows" \
    --objective i_standby_ua --direction min --target 25 --unit uA \
    --track wake_ms --track-limit wake_ms=10 --track-direction wake_ms=min --track-unit wake_ms=ms \
    --tool ngspice >/dev/null

iterate record standby --var ref_duty=1 --var c_ref_nf=100 \
    --metric i_standby_ua=31.8 --metric wake_ms=0.4 \
    --verdict fail --note "reference always on — the +40 C corner as built" \
    --evidence sim/standby/loop/pass-1.raw >/dev/null
iterate record standby --var ref_duty=0.017 --var c_ref_nf=100 \
    --metric i_standby_ua=5.9 --metric wake_ms=12.1 \
    --verdict partial --note "duty-cycle the reference: current solved, wake-up now over budget" \
    --evidence sim/standby/loop/pass-2.raw >/dev/null
iterate record standby --var ref_duty=0.017 --var c_ref_nf=10 \
    --metric i_standby_ua=6.4 --metric wake_ms=4.2 \
    --verdict pass --note "smaller reference bypass — settles in time, costs 0.5 uA" \
    --evidence sim/standby/loop/pass-3.raw >/dev/null
iterate record standby --var ref_duty=0.017 --var c_ref_nf=10 --var ldo_gated=1 \
    --metric i_standby_ua=5.1 --metric wake_ms=41.0 \
    --verdict fail --note "gating the LDO too: lowest current of the five, and four times over the wake budget" \
    --evidence sim/standby/loop/pass-4.raw >/dev/null
iterate record standby --var ref_duty=0.017 --var c_ref_nf=10 --var comparator=TS881 \
    --metric i_standby_ua=4.8 --metric wake_ms=4.4 \
    --verdict pass --note "lower-Iq comparator on the same topology as #3" \
    --evidence sim/standby/loop/pass-5.raw >/dev/null

iterate close standby --accept 3 --status converged \
    --note "took #3, not the 4.8 uA of #5: the TS881 is a second supplier for
            1.6 uA we do not need, and #3 already has 4x margin" >/dev/null
iterate chart standby --out docs/design/standby-evolution.svg >/dev/null
iterate status standby --gate >/dev/null \
    && echo "  loop gate clear — the accepted pass meets the target and names its run" \
    || echo "  LOOP GATE FAILED"

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

# Requested, waiting — a design loop asking a human to confirm the trade it made.
review open standby --title "Standby current, after five passes" \
    --summary "Duty-cycling the reference gets the +40 C corner to 6.4 uA. #5
was lower and #3 was faster to wake; I took #3." \
    --artifact docs/design/standby-evolution.svg \
    --artifact docs/design/standby-corners.svg \
    --reference docs/design/standby-results.md \
    --reference docs/design/iterations/standby.json \
    --question "Take #3 at 6.4 uA, or #5 at 4.8 uA for a second comparator part?" \
    --question "Is 4.2 ms wake-up inside what the one-minute log interval needs?" >/dev/null

echo
echo "== 6. re-render the plan, now that the reviews exist =="
plan --check && plan >/dev/null && echo "  plan renders clean"

echo
echo "== 7. the review page =="
"${PY}" "${S}/review_artifact.py"

echo
review list
