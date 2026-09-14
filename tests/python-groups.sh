#!/usr/bin/env bash
# Do env/setup.sh and hw-repair.sh still agree about what installs what?
#
# `hw-repair python <group>` re-runs one of phase_python's install groups. To
# do that it has to know the groups, and it cannot ask: setup.sh is pasted
# into the environment dialog as one self-contained file and cannot source
# anything from this repo, while hw-repair.sh ships inside the plugin. They
# are physically unable to share a definition.
#
# So the tables are duplicated, and this is what stops them drifting. The
# house rule is generated-or-checked, never hand-synced — a repair that
# installs a package set the build no longer uses is worse than no repair,
# because it reports success.
#
# The same applies to phase_base's apt list, which `hw-repair base` mirrors.
#
#   tests/python-groups.sh
#
# Needs python3. No network, no toolchain.
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cd "${ROOT}"
PY="${HARDWARE_PYTHON:-python3}"
SETUP="env/setup.sh"
REPAIR="plugins/makehardware/scripts/hw-repair.sh"

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }

echo "the python install groups"

"${PY}" - "${SETUP}" "${REPAIR}" <<'PYEOF'
import re, sys
setup, repair = (open(p).read() for p in sys.argv[1:3])

# phase_python's group lines: _uvpip "${VENV}" <group> <packages...>
built = {}
for m in re.finditer(r'^\s*_uvpip\s+"\$\{VENV\}"\s+(\S+)\s+([^|\n]+?)\s*(?:\|\||$)',
                     setup, re.M):
    built[m.group(1)] = tuple(m.group(2).split())

m = re.search(r'^PY_GROUPS="(.*?)"$', repair, re.S | re.M)
if not m:
    print("      hw-repair.sh has no PY_GROUPS table"); sys.exit(1)
known = {}
for line in m.group(1).strip().splitlines():
    g, pkgs, _probe = line.split(":", 2)
    known[g] = tuple(pkgs.split())

bad = []
for g in sorted(set(built) | set(known)):
    if g not in known:
        bad.append(f"setup.sh installs group '{g}' and hw-repair cannot repair it")
    elif g not in built:
        bad.append(f"hw-repair offers group '{g}' and setup.sh no longer installs it")
    elif built[g] != known[g]:
        bad.append(f"group '{g}': setup.sh installs {' '.join(built[g])}, "
                   f"hw-repair installs {' '.join(known[g])}")
if bad:
    print("\n".join("      " + b for b in bad)); sys.exit(1)
if not built:
    print("      no _uvpip group lines found in phase_python — has it been rewritten?")
    sys.exit(1)
PYEOF
[ $? -eq 0 ] \
    && pass "every group setup.sh installs, hw-repair can re-run, with the same packages" \
    || fail "the two group tables disagree"

echo
echo "the base package set"

"${PY}" - "${SETUP}" "${REPAIR}" <<'PYEOF'
import re, sys
setup, repair = (open(p).read() for p in sys.argv[1:3])

m = re.search(r'_apt install -y --no-install-recommends\s*\\\n(.*?)>\s*"\$\{LOGDIR\}/base\.log"',
              setup, re.S)
if not m:
    print("      could not find phase_base's apt install line"); sys.exit(1)
built = set()
for line in m.group(1).splitlines():
    line = line.strip().rstrip("\\").strip()
    if not line or line.startswith("#") or line.startswith('"$'):
        continue
    built.update(line.split())

m = re.search(r'^BASE_PKGS="(.*?)"$', repair, re.S | re.M)
if not m:
    print("      hw-repair.sh has no BASE_PKGS list"); sys.exit(1)
known = set(m.group(1).split())

missing, extra = sorted(built - known), sorted(known - built)
if missing:
    print(f"      phase_base installs, hw-repair base does not: {', '.join(missing)}")
if extra:
    print(f"      hw-repair base installs, phase_base does not: {', '.join(extra)}")
sys.exit(1 if (missing or extra) else 0)
PYEOF
[ $? -eq 0 ] \
    && pass "…and the base apt list is the same set on both sides" \
    || fail "phase_base and hw-repair base disagree about packages"

echo
echo "the sandbox prerequisite"

# bwrap is in the image; socat is not, and a sandboxed Bash run needs both.
# Without it the failure is a refusal to run, which reads as a broken eval.
# Match the apt line, not the comment above it — a mention is not an install.
grep -qE '^[[:space:]]+socat[[:space:]]*\\$' "${SETUP}" \
    && pass "phase_base still installs socat" \
    || fail "socat has gone from phase_base's apt list — sandboxed Bash needs it"

echo
echo "the line repairs must not claim to cross"

grep -q 'bootstrap' "${REPAIR}" \
    && pass "hw-repair still redirects 'bootstrap' to env/bootstrap.sh" \
    || fail "hw-repair no longer explains that it cannot bootstrap"

[ -x env/bootstrap.sh ] \
    && pass "…and env/bootstrap.sh exists and is executable" \
    || fail "env/bootstrap.sh is missing or not executable"

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
