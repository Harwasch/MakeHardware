#!/usr/bin/env bash
# Does every tool the plugin ships actually run without a permission prompt?
#
# `permissions.allow` is written out in three settings files and quoted in four
# markdown pages, and nothing kept them in step. By 0.8.0 six of the fourteen
# tools on PATH were missing from every copy — `sch-lint`, `pcb-lint`,
# `hw-chart`, `cad-export`, `review-artifact` and `hw-iterate`, which is to say
# every gate added after the list was first written. The cost is not one
# prompt: it is that the gates are the things an agent runs most often, so the
# omission taxed exactly the workflow the gates exist to enforce.
#
# Two tools are left out on purpose and this test asserts they stay out:
#
#   hw-repair     adds apt sources, imports GPG keys and installs packages as
#                 root. Auto-allowing it lets an unattended agent install from
#                 a PPA with nobody watching. The prompt IS the review, and a
#                 ninety-second fix does not outweigh it.
#   build123d-mcp an MCP server, started by the client from .mcp.json. It is
#                 never a Bash call.
#
# One thing this cannot fix, and the doc says so too: in a cloud session the
# workspace is untrusted, and an untrusted workspace ignores project-scope
# `permissions.allow` entirely. See docs/01-environment.md. The durable fix is
# at user scope from the setup script.
#
#   tests/settings-allowlist.sh
#
# Needs python3. No network, no toolchain.
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cd "${ROOT}"
PY="${HARDWARE_PYTHON:-python3}"

SETTINGS=(
    ".claude/settings.json"
    "plugins/makehardware/templates/project/.claude/settings.json"
    "templates/github-repo/.claude/settings.json"
)
# Pages that quote the snippet. Drift here is how a user ends up pasting a
# list that no longer matches the tools they were given.
PAGES=(
    "README.md"
    "docs/01-environment.md"
    "docs/03-using-it.md"
    "plugins/makehardware/commands/hw-new-project.md"
)
DENY=("hw-repair" "build123d-mcp")

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }
skip() { printf '  \033[33m--\033[0m    %s\n' "$1"; }

echo "the tools on PATH"

"${PY}" - "${DENY[@]}" -- "${SETTINGS[@]}" <<'PYEOF'
import json, os, sys
deny = set(sys.argv[1:sys.argv.index("--")])
files = sys.argv[sys.argv.index("--") + 1:]
want = {f"Bash({n}:*)" for n in os.listdir("plugins/makehardware/bin")} - \
       {f"Bash({n}:*)" for n in deny}
bad = []
for f in files:
    allow = set(json.load(open(f))["permissions"]["allow"])
    missing = sorted(want - allow)
    present = sorted({f"Bash({n}:*)" for n in deny} & allow)
    if missing:
        bad.append(f"{f}: missing {', '.join(missing)}")
    if present:
        bad.append(f"{f}: must NOT allow {', '.join(present)} — read this file's header")
if bad:
    print("\n".join("      " + b for b in bad))
    sys.exit(1)
PYEOF
[ $? -eq 0 ] \
    && pass "every bin/ tool is allowed in all three settings files" \
    || fail "a tool on PATH is missing from an allowlist, or a denied one is in"

"${PY}" - "${SETTINGS[@]}" <<'PYEOF'
import json, sys
sets = [frozenset(json.load(open(f))["permissions"]["allow"]) for f in sys.argv[1:]]
if len(set(sets)) != 1:
    base = sets[0]
    for f, s in zip(sys.argv[1:], sets):
        d = sorted(s ^ base)
        if d:
            print(f"      {f} differs by: {', '.join(d)}")
    sys.exit(1)
PYEOF
[ $? -eq 0 ] \
    && pass "…and the three lists are the same set" \
    || fail "the three allowlists have drifted apart"

echo
echo "the pages that quote it"

"${PY}" - "${PAGES[@]}" <<'PYEOF'
import json, os, re, sys
known = {f"Bash({n}:*)" for n in os.listdir("plugins/makehardware/bin")}
known |= set(json.load(open(".claude/settings.json"))["permissions"]["allow"])
bad = []
for f in sys.argv[1:]:
    if not os.path.exists(f):
        continue
    for m in set(re.findall(r'"(Bash\([^"]+\))"', open(f).read())):
        if m not in known:
            bad.append(f"{f}: quotes {m}, which is not a tool or an allowed entry")
if bad:
    print("\n".join("      " + b for b in bad))
    sys.exit(1)
PYEOF
[ $? -eq 0 ] \
    && pass "no page quotes an allowlist entry that does not exist" \
    || fail "a doc page quotes a stale allowlist entry"

echo
echo "the cloud caveat is still written down"

if grep -q "hasTrustDialogAccepted" docs/01-environment.md; then
    pass "docs/01-environment.md still says project allowlists are ignored untrusted"
else
    fail "the untrusted-workspace caveat has gone from docs/01-environment.md"
fi

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
