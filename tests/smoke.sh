#!/usr/bin/env bash
# Smoke test for the MakeHardware tooling.
#
# Scaffolds a throwaway project from templates/project and drives it through
# the gates that matter — the ones that used to have nothing behind them:
# a `done` claim with no outputs, a `done` claim with no sign-off, and an
# artefact edited after the human agreed to it.
#
#   tests/smoke.sh                 # uses python3 from PATH
#   HARDWARE_PYTHON=/opt/hw-py/bin/python tests/smoke.sh
#
# Needs python3 with pyyaml. The strictdoc-backed parts of req-trace are not
# exercised here; its renderer is, with synthetic requirements.
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
S="${ROOT}/plugins/makehardware/scripts"
PY="${HARDWARE_PYTHON:-python3}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/mh-smoke.XXXXXX")
trap 'rm -rf "${WORK}"' EXIT

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }
check() { if "$@" >/dev/null 2>&1; then return 0; else return 1; fi; }
# `set -o pipefail` reports the pipeline's first non-zero status, so
# `a-failing-command | grep -q x` reads as a failure even when grep matched.
# Every check here runs a command that is *meant* to exit 1, so capture the
# output and match it separately.
says() {  # says <pattern> <command...>
    local want=$1; shift
    local out
    out=$("$@" 2>&1)
    [[ ${out} == *"${want}"* ]]
}

cd "${WORK}"
cp -r "${ROOT}/plugins/makehardware/templates/project/." .
git init -q .
git remote add origin https://github.com/Harwasch/smoke-test.git
printf '# Smoke\n\n<!-- PLAN:BEGIN -->\n<!-- PLAN:END -->\n' > README.md
git add -A && git -c user.email=t@t -c user.name=t commit -qm scaffold

echo "MakeHardware smoke test"
echo

echo "plan-render"
check "${PY}" "${S}/plan_render.py" --check \
    && pass "the scaffolded template validates" \
    || fail "the scaffolded template does not validate"

"${PY}" "${S}/plan_render.py" >/dev/null 2>&1
for f in docs/plan.svg docs/plan.md docs/plan.drawio; do
    [ -s "${f}" ] && pass "wrote ${f}" || fail "${f} missing or empty"
done
grep -q 'PLAN:BEGIN' README.md && pass "README block injected" \
    || fail "README block not injected"
grep -q 'Statuses are deliberately not in this file' docs/plan.md \
    && pass "scope document carries no statuses" \
    || fail "scope document is not status-free"

echo
echo "review gate"
check "${PY}" "${S}/review_gate.py" check --gate \
    && fail "gate passed with nothing reviewed" \
    || pass "gate refuses a project with no reviews"

"${PY}" - <<'PYEOF'
import yaml
p = yaml.safe_load(open("plan.yaml"))
for c in p["chunks"]:
    if c["id"] == "V1":
        c["status"] = "done"
yaml.safe_dump(p, open("plan.yaml", "w"), sort_keys=False)
PYEOF

check "${PY}" "${S}/plan_render.py" --check \
    && fail "a done chunk with missing outputs was accepted" \
    || pass "done with missing outputs is refused"

mkdir -p docs/design/vision
printf '# Vision\n' > docs/design/vision.md
printf 'render\n' > docs/design/vision/hero.png
says 'never been requested' "${PY}" "${S}/plan_render.py" --check \
    && pass "done with an unrequested review is refused" \
    || fail "the review was not checked"

git add -A && git -c user.email=t@t -c user.name=t commit -qm vision
"${PY}" "${S}/review_gate.py" open vision \
    --artifact docs/design/vision.md --artifact docs/design/vision/ >/dev/null
"${PY}" "${S}/review_gate.py" sign vision --approve --by smoke --note "B" >/dev/null

check "${PY}" "${S}/plan_render.py" --check \
    && pass "a signed review clears plan-render --check" \
    || fail "plan-render still failing after sign-off"
check "${PY}" "${S}/review_gate.py" check vision --gate \
    && pass "a signed review clears review-gate" \
    || fail "review-gate still failing after sign-off"

"${PY}" "${S}/review_gate.py" open vision \
    --artifact docs/design/vision.md >/dev/null 2>&1
grep -q 'What you are agreeing to' docs/review/vision.md \
    && pass "the packet separates the agreement from the context" \
    || fail "the packet does not label the agreement"

printf '# Vision, rewritten\n' > docs/design/vision.md
"${PY}" "${S}/review_gate.py" sign vision --approve --by smoke >/dev/null
printf '# Vision, rewritten again\n' > docs/design/vision.md
check "${PY}" "${S}/review_gate.py" check vision --gate \
    && fail "a changed artefact did not make the review stale" \
    || pass "editing a signed artefact makes the review stale"
says 'changed' "${PY}" "${S}/plan_render.py" --check \
    && pass "staleness reaches plan-render --check" \
    || fail "staleness does not reach the plan"

echo
echo "block-diagram power budget"
cat > bd.yaml <<'YEOF'
project: Referral test
rails:
  - {id: HV400, voltage: 400, source: J1, max_current_a: 10.0}
  - {id: LV48, voltage: 48, from: HV400, source: U1, max_current_a: 70.0}
blocks:
  - {id: J1, name: DC input, kind: connector}
  - id: U1
    name: Isolated DAB
    kind: regulator
    powered_by: [{rail: HV400, typ_current_a: 0.05, max_current_a: 0.10}]
  - id: M1
    name: Inverter
    kind: actuator
    powered_by: [{rail: LV48, typ_current_a: 40.0, max_current_a: 67.0}]
buses:
  - {id: CAN1, kind: can, between: [U1, M1]}
YEOF
# 67 A at 48 V is 8.04 A off a 400 V input, not 67 A. Adding the amps
# straight on declared the parent rail 8x over budget when it was fine.
bd_out=$("${PY}" "${S}/block_diagram.py" bd.yaml --summary 2>/dev/null)
grep -qE 'HV400 +400 +4\.850 +8\.140' <<<"${bd_out}" \
    && pass "child rail current is referred through the voltage ratio" \
    || fail "the budget roll-up is not referring through the voltage ratio"

echo
echo "renderers"
"${PY}" - "${S}" <<'PYEOF'
import sys, os
sys.path.insert(0, sys.argv[1])
import xml.etree.ElementTree as ET
import req_trace as rt

def R(uid, title, status="Draft", parents=(), ev="", files=(), ver="Analysis"):
    return {"uid": uid, "title": title, "doc": "d", "status": status,
            "verification": ver, "evidence": ev, "budget": "",
            "parents": list(parents), "files": list(files)}

reqs = [R("VIS-001", "A week on one charge"),
        R("SYS-001", "12 h at 25 degC", "Agreed", ["VIS-001"]),
        R("SYS-009", "Nobody asked for this"),
        R("ELE-001", "<= 40 uA standby", "Verified", ["SYS-001"],
          ev="sim/run.log", files=["hw/p.kicad_sch"], ver="Simulation"),
        R("MEC-002", "IP54", "Draft", ["SYS-001"], ver="Test")]
a = rt.analyse(reqs)
rt.write_map(reqs, a, "map.svg", "map.drawio")
for f in ("map.svg", "map.drawio"):
    ET.parse(f)
assert "SYS-009" in open("map.drawio").read()
assert "refines nothing" in open("map.svg").read(), "gaps are not marked"
print("MAP OK")
PYEOF
[ $? -eq 0 ] && pass "requirements map renders valid SVG and draw.io" \
             || fail "requirements map failed"

# ---------------------------------------------------------------------------
# The review page's two once-per-project setup steps. Both are easy to skip and
# expensive to skip: without `--init` no design stage ever appears on the page,
# and without `--url` every session publishes a *second* page, so the human
# ends up reading whichever one they bookmarked.
# ---------------------------------------------------------------------------
echo
echo "review page setup"

INITDIR="${WORK}/initproj"
mkdir -p "${INITDIR}/docs/design/cad"
( cd "${INITDIR}" && git init -q . \
  && git remote add origin https://github.com/Harwasch/smoke-widget.git \
  && printf 'project: Smoke Widget\nchunks: []\n' > plan.yaml \
  && printf '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40" \
viewBox="0 0 80 40"><rect width="80" height="40" fill="none"/></svg>\n' \
     > docs/design/cad/enclosure-section.svg ) >/dev/null 2>&1

says "wrote docs/review/artifact.yaml" \
    "${PY}" "${S}/review_artifact.py" --project "${INITDIR}" --init \
    && pass "--init writes a starter config" \
    || fail "--init wrote nothing"

# A phase whose artefacts exist is live; the rest arrive commented, so nobody
# has to remember that a `layout` phase was ever an option.
CFG="${INITDIR}/docs/review/artifact.yaml"
grep -qE '^  - id: cad'    "${CFG}" && pass "a stage with artefacts is enabled" \
                                    || fail "cad should have been enabled"
grep -qE '^#   - id: layout' "${CFG}" && pass "a stage without them is commented" \
                                      || fail "layout should have been commented"
"${PY}" -c "import yaml,sys; d=yaml.safe_load(open('${CFG}'))
assert [p['id'] for p in d['phases']] == ['cad','mfg'], d
assert len(d['phases'][-1]['links']) == 10" \
    && pass "the generated config parses and carries the mfg checklist" \
    || fail "generated config is not valid"

says "already exists" \
    "${PY}" "${S}/review_artifact.py" --project "${INITDIR}" --init \
    && pass "--init refuses to overwrite" || fail "--init clobbered the config"

says "does not look like" \
    "${PY}" "${S}/review_artifact.py" --project "${INITDIR}" \
    --url "http://evil.example/x" \
    && pass "--url rejects a non-artifact URL" || fail "--url accepted junk"

U="https://claude.ai/code/artifact/ef071485-7196-44c0-81b3-e65facefc4cb"
"${PY}" "${S}/review_artifact.py" --project "${INITDIR}" --url "${U}" \
    >/dev/null 2>&1
says "updates in place" \
    "${PY}" "${S}/review_artifact.py" --project "${INITDIR}" \
    && pass "a recorded URL is played back for the next publish" \
    || fail "the recorded artifact URL was not read back"


# ---------------------------------------------------------------------------
# The design gates: sch-lint, pcb-lint, cad-export, hw-chart.
#
# Every one runs against real tool output rather than something we wrote. A
# linter validated against a file its own author typed is a linter that agrees
# with itself. The schematic is KiCad's own pic_programmer demo, the board is
# generated by pcbnew, and the assembly is the example's real build123d module.
# ---------------------------------------------------------------------------
echo
echo "== design gates =="
DEMO="${ROOT}/examples/thermal-probe/hw/kicad-demo/pic_programmer.kicad_sch"
BOARD="${ROOT}/examples/thermal-probe/hw/lint-fixture.kicad_pcb"
ENC="${ROOT}/examples/thermal-probe/cad/enclosure.py"

# The reader handles both dialects present in this repo: the KiCad 7 schematic
# above (space-indented, one-line nodes) and KiCad 9/10 boards (tabs, one atom
# per line). Format drift is the thing most likely to break these scripts.
check "${PY}" "${S}/kicad_sexpr.py" "${DEMO}" \
    && pass "the S-expression reader parses a KiCad 7 schematic" \
    || fail "kicad_sexpr could not read the demo schematic"
if [ -f "${BOARD}" ]; then
    check "${PY}" "${S}/kicad_sexpr.py" "${BOARD}" \
        && pass "…and a KiCad 10 board" \
        || fail "kicad_sexpr could not read the board fixture"
fi

# The load-bearing piece of sch_lint is the library-to-sheet pin transform:
# library coordinates are +Y up, the sheet is +Y down, and mirror composes with
# rotation in an order that is easy to reverse. Get it wrong and five checks
# are silently garbage while still emitting plausible findings. The proof is
# that every computed pin lands on the 1.27 mm grid — no other sign convention
# does that, and it needs no hand-written expected values.
cat > "${WORK}/pins.py" <<'PINCHECK'
import sys
sys.path.insert(0, sys.argv[1])
import sch_lint as L
sheets = L.load_hierarchy(sys.argv[2])
pins = [p for sh in sheets for s in sh.symbols for p in s["pins"]]
off = [p for p in pins if not (L.ongrid(p["sx"]) and L.ongrid(p["sy"]))]
assert pins, "no pins found at all"
assert not off, f"{len(off)} of {len(pins)} computed pins are off grid"
PINCHECK
check "${PY}" "${WORK}/pins.py" "${S}" "${DEMO}" \
    && pass "every computed pin lands on the grid" \
    || fail "the library-to-sheet pin transform is wrong"

# The finished demo must be silent on the geometric checks. A gate that fires
# on clean work is a gate somebody switches off inside a week.
out=$("${PY}" "${S}/sch_lint.py" "${DEMO}" --no-export \
      --only SCH-GRID,SCH-DIAG,SCH-SHEETPIN,SCH-OVERLAP 2>&1)
case "${out}" in
  *"Nothing to report"*) pass "sch-lint is quiet on a clean drawing" ;;
  *) fail "sch-lint reported geometry findings on a clean demo" ;;
esac

# And it must find what is really there: the root sheet is rev 2 and the child
# is rev 3, in the committed fixture.
out=$("${PY}" "${S}/sch_lint.py" "${DEMO}" --no-export --only SCH-REVSKEW 2>&1)
case "${out}" in
  *"different revisions"*) pass "sch-lint finds the revision skew in the fixture" ;;
  *) fail "sch-lint missed the rev 2 / rev 3 skew" ;;
esac

"${PY}" "${S}/sch_lint.py" "${DEMO}" --no-export --json 2>/dev/null > "${WORK}/l.json"
check "${PY}" -c "import json,sys; d=json.load(open('${WORK}/l.json')); assert d['findings']" \
    && pass "sch-lint --json is machine-readable" \
    || fail "sch-lint --json did not produce usable JSON"

"${PY}" "${S}/sch_lint.py" "${DEMO}" --no-export --svg "${WORK}/lint" >/dev/null 2>&1
check "${PY}" -c "
import glob, xml.etree.ElementTree as ET
f = sorted(glob.glob('${WORK}/lint/*.svg'))
assert f, 'no overlay written'
ET.parse(f[0])" \
    && pass "the sch-lint overlay is well-formed SVG" \
    || fail "the sch-lint overlay does not parse"

# The board fixture carries, in real geometry, the defects pcb-layout.md was
# written about. If pcb-lint stops finding them, one of the two is wrong.
if [ -f "${BOARD}" ]; then
    b=$("${PY}" "${S}/pcb_lint.py" "${BOARD}" 2>&1)
    for want in PCB-THERMVIA PCB-TRACKW PCB-CLEAR; do
        case "${b}" in
          *"${want}"*) pass "pcb-lint finds ${want} in the fixture" ;;
          *) fail "pcb-lint missed ${want}" ;;
        esac
    done
    if "${PY}" "${S}/pcb_lint.py" "${BOARD}" --gate >/dev/null 2>&1; then
        fail "pcb-lint --gate passed a board with shorts on it"
    else
        pass "pcb-lint --gate fails on the defective board"
    fi
else
    echo "  (no board fixture — skipping pcb-lint)"
fi

# cad-export's gate is about whether the file is usable by whoever opens it.
if "${PY}" -c "import build123d" >/dev/null 2>&1; then
    check "${PY}" "${S}/cad_export.py" "${ENC}" --check \
        && pass "cad-export --check passes on a real assembly" \
        || fail "the example assembly does not satisfy its own gate"
    printf 'from build123d import *\nPART = Box(10, 10, 10)\n' > "${WORK}/lump.py"
    if "${PY}" "${S}/cad_export.py" "${WORK}/lump.py" --check >/dev/null 2>&1; then
        fail "cad-export accepted a single unnamed solid"
    else
        pass "cad-export --check rejects a single unnamed solid"
    fi
else
    echo "  (no build123d — skipping cad-export)"
fi

# Charts: valid, light enough for the review page, and carrying the failure
# they are about rather than leaving the reader to find it.
printf 'name,used,budget,unit\nA,9,10,mA\nB,12,10,mA\n' > "${WORK}/b.csv"
"${PY}" "${S}/charts.py" budget "${WORK}/b.csv" --out "${WORK}/b.svg" >/dev/null 2>&1
check "${PY}" -c "
import xml.etree.ElementTree as ET
t = open('${WORK}/b.svg').read()
ET.fromstring(t)
assert 'OVER by' in t, 'the over-budget row is not called out'
assert t.count('<') < 220, 'chart is too heavy for the review page'" \
    && pass "hw-chart budget is valid SVG and names the overage" \
    || fail "hw-chart budget output is wrong"

echo
echo "== the KiCad channel =="

# 0.7.0 replaced Konnect with ki-stack. The regression these guard against is a
# half-migration: guidance that still tells an agent to route every `.kicad_*`
# change through MCP tools the plugin no longer registers, which reads to the
# agent as a broken environment rather than as stale advice.
check "${PY}" -c "
import json
d = json.load(open('${ROOT}/plugins/makehardware/.mcp.json'))
assert 'konnect' not in d['mcpServers'], d['mcpServers']" \
    && pass "the plugin registers no konnect MCP server" \
    || fail "konnect is still in .mcp.json"

# kicad-channels.md is excluded by name: its whole job is to say that the old
# rule is stale, so it quotes it, and a grep cannot tell a quotation from an
# instruction.
stale=$(grep -rl "Konnect MCP\|through \*\*Konnect\*\*\|konnect__" \
    "${ROOT}/plugins/makehardware/skills" 2>/dev/null \
    | grep -v "kicad-channels.md" | wc -l)
[ "${stale}" -eq 0 ] \
    && pass "no skill routes KiCad edits through Konnect" \
    || fail "${stale} skill(s) still route edits through Konnect"

check "${PY}" -c "
import json
json.load(open('${ROOT}/plugins/makehardware/templates/kicad/house-defaults.json'))" \
    && pass "the house KiCad defaults parse as JSON a .kicad_pro can take" \
    || fail "house-defaults.json is missing or malformed"

# The rule that did NOT change. A hand-rolled text edit corrupts these files
# whatever drives the toolchain, and the reader must stay a reader.
# Its docstring, not a --help flag: this module has no CLI beyond "parse the
# file named in argv[1]", and asserting on a flag it does not have was a test
# bug, not a finding.
check "${PY}" -c "
import ast, pathlib
doc = ast.get_docstring(ast.parse(pathlib.Path('${S}/kicad_sexpr.py').read_text()))
assert 'read-only' in doc.lower(), doc.splitlines()[0]
assert 'nothing writes' in doc.lower()" \
    && pass "the S-expression module still describes itself as read-only" \
    || fail "kicad_sexpr.py no longer states that it only reads"

echo
echo "== the closed design loop =="

# hw-iterate is the ledger a review's evolution chart is drawn from, so the
# things checked here are the ones that make it trustworthy rather than
# decorative: engineering notation read as written, an objective that must be
# measured, and a gate that refuses an unattributed claim.
L="${WORK}/loops"
check "${PY}" "${S}/iterate.py" --dir "${L}" open margin \
    --goal "phase margin over 60 deg" --objective pm --direction max \
    --target 60 --unit deg --track bw --track-limit bw=1M --track-unit bw=Hz \
    && pass "a loop opens with an objective and a limit it must not cost" \
    || fail "hw-iterate open failed"

says "objective" "${PY}" "${S}/iterate.py" --dir "${L}" record margin \
    --metric bw=1.2M --verdict fail \
    && pass "a pass that never measured the objective is refused" \
    || fail "a pass with no objective metric was accepted"

"${PY}" "${S}/iterate.py" --dir "${L}" record margin --var Cc=4.7p \
    --metric pm=31 --metric bw=2.1M --verdict fail --note base >/dev/null 2>&1
"${PY}" "${S}/iterate.py" --dir "${L}" record margin --var Cc=1k5 \
    --metric pm=66 --metric bw=1.35M --verdict pass --note zero >/dev/null 2>&1
check "${PY}" -c "
import json
d = json.load(open('${L}/margin.json'))
v = [i['vars'] for i in d['iterations']]
assert v[0]['Cc'] == 4.7e-12, v[0]
assert v[1]['Cc'] == 1500.0, v[1]     # RKM: 1k5 is 1500, not the string '1k5'
assert d['iterations'][1]['metrics']['bw'] == 1.35e6" \
    && pass "engineering and RKM notation are read as numbers" \
    || fail "hw-iterate mis-parsed an engineering value"

# The gate is the whole point: a number nobody can trace to a run is not
# evidence, however good it looks on the chart.
"${PY}" "${S}/iterate.py" --dir "${L}" close margin --accept 2 \
    --status converged >/dev/null 2>&1
says "no evidence" "${PY}" "${S}/iterate.py" --dir "${L}" status margin --gate \
    && pass "the loop gate refuses an accepted pass with no evidence" \
    || fail "the loop gate passed an unattributed claim"

touch "${WORK}/run.raw"
"${PY}" "${S}/iterate.py" --dir "${L}" record margin --var Cc=1k5 \
    --metric pm=66 --metric bw=1.35M --verdict pass --note zero \
    --evidence "${WORK}/run.raw" >/dev/null 2>&1
"${PY}" "${S}/iterate.py" --dir "${L}" close margin --accept 3 \
    --status converged >/dev/null 2>&1
check "${PY}" "${S}/iterate.py" --dir "${L}" status margin --gate \
    && pass "…and clears once the accepted pass names its run file" \
    || fail "the loop gate failed a properly attributed loop"

"${PY}" "${S}/iterate.py" --dir "${L}" chart margin \
    --out "${WORK}/evo.svg" >/dev/null 2>&1
check "${PY}" -c "
import xml.etree.ElementTree as ET
t = open('${WORK}/evo.svg').read()
ET.fromstring(t)
assert 'accepted' in t, 'the accepted iteration is not marked'
assert 'min 60 deg' in t, 'the target line is not drawn'
assert '2.1MHz' in t, 'a large value was not SI-prefixed and will overrun its axis'
assert t.count('<') < 400, 'chart is too heavy for the review page'" \
    && pass "the evolution chart draws the target, the accepted pass and SI units" \
    || fail "the evolution chart output is wrong"

echo
echo "== review concision =="

# The budget exists because a review that is mostly prose gets skimmed, and a
# skimmed review is a sign-off nobody really gave.
cd "${WORK}"
LONG=$("${PY}" -c "print(' '.join(['word'] * 90))")
says "not opened" "${PY}" "${S}/review_gate.py" open architecture \
    --title T --summary "${LONG}" --artifact docs/plan.svg \
    && pass "a review whose summary blows the word budget is refused" \
    || fail "an over-long summary was accepted"

says "not opened" "${PY}" "${S}/review_gate.py" open architecture \
    --title T --summary "Three rails." --artifact docs/plan.svg \
    --question "${LONG}" \
    && pass "…and so is one whose question does" \
    || fail "an over-long question was accepted"

check "${PY}" "${S}/review_gate.py" open architecture --title T \
    --summary "Three rails off one buck. 3V3_ANA is the tight one." \
    --artifact docs/plan.svg --question "Split the analogue rail?" \
    && pass "a review that leads with the figure opens" \
    || fail "a concise review was refused"

echo
if [ "${fails}" -eq 0 ]; then
    echo "all checks passed"
else
    echo "${fails} check(s) failed"
fi
[ "${fails}" -eq 0 ]
