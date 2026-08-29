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

echo
if [ "${fails}" -eq 0 ]; then
    echo "all checks passed"
else
    echo "${fails} check(s) failed"
fi
[ "${fails}" -eq 0 ]
