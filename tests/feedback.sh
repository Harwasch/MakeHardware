#!/usr/bin/env bash
# Does a finding about the toolbox actually reach the toolbox?
#
# `hw-retro` told the agent to "offer to file the proposed changes as a GitHub
# issue" for four releases and named no mechanism. There was none: `gh` is not
# in the environment, and a cloud session's token is scoped to the project
# repo, so it cannot reach the plugin's repo at all. Every retro that ever ran
# ended by offering something impossible.
#
# So this checks the parts that are silent when they break:
#
#   1. The structural gate. An observation without a named file is not
#      actionable — the tool has to refuse one, or the records fill with
#      "the sourcing skill should be better".
#   2. The URL round-trip. GitHub prefills an issue *form* by matching the
#      query parameter name against the element's `id`. Get a name wrong and
#      the field renders blank with no error on any side.
#   3. Dropdown values are exact-match, and also fail silently. A `kind` the
#      form does not declare is simply not applied.
#   4. The URL budget. Percent-encoding inflates markdown 1.8-3.0x and
#      github.com answers an over-long GET with 414, so the tool sheds fields
#      rather than emitting a link that dies on click.
#
#   tests/feedback.sh
#
# Needs python3. No network, no toolchain, no `gh`.
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
S="${ROOT}/plugins/makehardware/scripts"
FORM="${ROOT}/.github/ISSUE_TEMPLATE/engineering-system-feedback.yml"
PY="${HARDWARE_PYTHON:-python3}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/mh-feedback.XXXXXX")
trap 'rm -rf "${WORK}"' EXIT

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }

# `set -o pipefail` reports a pipeline's first non-zero status, so
# `a-failing-command | grep -q x` reads as a failure even when grep matched.
# Every gate check below runs a command that is *meant* to exit 1.
says() {  # says <pattern> <command...>
    local want=$1; shift
    local out
    out=$("$@" 2>&1)
    [[ ${out} == *"${want}"* ]]
}

cd "${WORK}"
git init -q .
git remote add origin https://github.com/someone/widget.git
FB=("${PY}" "${S}/hw_feedback.py")

echo "the structural gate"

says "not actionable" "${FB[@]}" new --file skills/no/such.md \
    --title t --edit e --evidence v \
    && pass "a finding naming a file that does not exist is refused" \
    || fail "a finding naming a file that does not exist was accepted"

says "--edit is empty" "${FB[@]}" new \
    --file skills/hw-sourcing/references/connectors.md \
    --title t --edit "   " --evidence v \
    && pass "…and one that says a change is needed without saying what" \
    || fail "an empty --edit was accepted"

says "--evidence is empty" "${FB[@]}" new \
    --file skills/hw-sourcing/references/connectors.md \
    --title t --edit e --evidence "  " \
    && pass "…and one with no evidence behind it" \
    || fail "an empty --evidence was accepted"

"${FB[@]}" new --file plugins/makehardware/skills/hw-visuals/SKILL.md \
    --title "Repo-prefixed paths are accepted" --edit e --evidence v >/dev/null 2>&1 \
    && pass "a plugins/makehardware/-prefixed path resolves too" \
    || fail "a repo-prefixed path was refused"

echo
echo "the record"

"${FB[@]}" new \
    --file skills/hw-sourcing/references/connectors.md \
    --title "Connector choice is relitigated every project" \
    --edit "Fill in the board-to-wire row with Molex PicoBlade, and say why." \
    --evidence "friction log 2026-08-28; commits a1b2c3, d4e5f6" \
    --cost "about one session" --kind "Missing guidance" >/dev/null 2>&1
REC="docs/design/feedback/$(date +%F)-connector-choice-is-relitigated-every-project.md"
[ -s "${REC}" ] \
    && pass "the record lands in the project repo" \
    || fail "no record at ${REC}"

grep -q '^published:$' "${REC}" \
    && pass "…and starts unpublished" \
    || fail "a new record is not marked unpublished"

says "not published" "${FB[@]}" list \
    && pass "…and list says so" \
    || fail "list does not report the unpublished record"

echo
echo "the prefilled issue"

SLUG=$(basename "${REC}" .md)
"${FB[@]}" publish "${SLUG}" --no-file >"${WORK}/pub.txt" 2>&1
grep -q "NOT FILED" "${WORK}/pub.txt" \
    && pass "publish says NOT FILED — it prepares, it does not file" \
    || fail "publish did not say NOT FILED"

grep -q -- "--- copy from here ---" "${WORK}/pub.txt" \
    && pass "…and prints the body, because the form carries a summary only" \
    || fail "publish printed no pasteable body"

grep -q "friction log 2026-08-28" "${WORK}/pub.txt" \
    && pass "…with the evidence inlined, not linked to a private repo" \
    || fail "evidence was not inlined in the body"

"${PY}" - "${FORM}" "${WORK}/pub.txt" <<'PYEOF'
import re, sys
from urllib.parse import urlparse, parse_qs
form, pub = sys.argv[1], sys.argv[2]
url = re.search(r"(https://github\.com/\S+/issues/new\?\S+)", open(pub).read())
if not url:
    print("NOURL"); sys.exit(1)
q = parse_qs(urlparse(url.group(1)).query, keep_blank_values=True)
text = open(form).read()
ids = set(re.findall(r"^\s*id:\s*(\S+)\s*$", text, re.M))
opts = set(re.findall(r"^\s{8}- (.+)$", text, re.M))
unknown = set(q) - ids - {"template", "title", "labels"}
if unknown:
    print("UNKNOWN", ",".join(sorted(unknown))); sys.exit(1)
if q.get("edit", [""])[0][:20] != "Fill in the board-to":
    print("MANGLED"); sys.exit(1)
if q.get("kind", [""])[0] not in opts:
    print("BADKIND", q.get("kind")); sys.exit(1)
sys.exit(0)
PYEOF
rc=$?
[ "${rc}" -eq 0 ] \
    && pass "every query parameter names a real field id, and the text survives" \
    || fail "the prefill URL does not match the form's field ids"

# The same agreement from the other side: the constants the script prefills
# with are the ones the form declares. Add a dropdown option to one and not
# the other and the field silently renders blank.
"${PY}" - "${FORM}" "${S}/hw_feedback.py" <<'PYEOF'
import re, sys
form, script = (open(p).read() for p in sys.argv[1:3])
form_ids = set(re.findall(r"^\s*id:\s*(\S+)\s*$", form, re.M))
form_opts = set(re.findall(r"^\s{8}- (.+)$", form, re.M))
m = re.search(r"^FIELDS = \((.*?)\)", script, re.S | re.M)
s_ids = set(re.findall(r'"([^"]+)"', m.group(1)))
m = re.search(r"^KINDS = \((.*?)\)", script, re.S | re.M)
s_opts = set(re.findall(r'"([^"]+)"', m.group(1)))
if s_ids != form_ids:
    print("IDS", sorted(s_ids ^ form_ids)); sys.exit(1)
if s_opts != form_opts:
    print("OPTS", sorted(s_opts ^ form_opts)); sys.exit(1)
sys.exit(0)
PYEOF
rc=$?
[ "${rc}" -eq 0 ] \
    && pass "…and FIELDS/KINDS in the script still agree with the .yml" \
    || fail "the script and the issue form disagree about fields or kinds"

echo
echo "the URL budget"

BIG=$("${PY}" -c "print('A worked example with real numbers is needed here. ' * 200)")
"${FB[@]}" new --file skills/hw-pcb-layout/SKILL.md \
    --title "Decoupling rule needs a worked example" \
    --edit "${BIG}" --evidence "${BIG}" >/dev/null 2>&1
"${FB[@]}" publish --no-file --separate >"${WORK}/big.txt" 2>&1
"${PY}" -c "
import re,sys
u=re.findall(r'https://github\.com/\S+/issues/new\?\S+', open('${WORK}/big.txt').read())
sys.exit(0 if u and max(len(x) for x in u) < 6000 else 1)"
[ $? -eq 0 ] \
    && pass "a finding far past the URL budget still yields a clickable link" \
    || fail "an oversize finding produced a URL over the budget"

grep -q "A worked example with real numbers" "${WORK}/big.txt" \
    && pass "…and the full text is still printed for paste" \
    || fail "the oversize body was not printed"

echo
echo "closing the loop"

"${FB[@]}" mark "$(basename "${REC}" .md)" \
    https://github.com/Harwasch/MakeHardware/issues/7 >/dev/null 2>&1
grep -q '^published: https://github.com/Harwasch/MakeHardware/issues/7$' "${REC}" \
    && pass "mark writes the issue url back into the record" \
    || fail "mark did not record where the issue went"

says "MakeHardware/issues/7" "${FB[@]}" list \
    && pass "…and list shows it against that issue" \
    || fail "list does not show the marked record's issue"

says "nothing to publish" "${FB[@]}" publish "${SLUG}" --no-file \
    && pass "…and publish will not offer it a second time" \
    || fail "publish re-offered a record that was already marked"

says "uncommitted" "${FB[@]}" check \
    && pass "check names records git does not have yet" \
    || fail "check did not flag the uncommitted records"

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
