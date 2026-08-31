#!/usr/bin/env bash
# Did the plugin change without its version moving?
#
# This exists because it already happened. `0.1.0` was set in the commit that
# first made this a plugin and was still `0.1.0` twenty-nine commits later,
# across an entire new subsystem. Nothing caught it, because nothing was
# looking — and the cost is not cosmetic:
#
#   `claude plugin install` treats an already-installed plugin at the same
#   version as nothing to do. So a user who runs `claude plugin marketplace
#   update makehardware` on a stale environment fetches the new source, sees a
#   version it already has, and keeps running the old plugin. The update
#   silently no-ops, and they debug behaviour from code they are not running.
#
# The version is also written in two files, which is its own way to be wrong:
# the marketplace entry is what a client reads to decide it has work to do, and
# the plugin manifest is what it records afterwards. They must agree.
#
#   tests/version-bump.sh [<base-ref>]      # default: origin/main
set -uo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cd "${ROOT}"

MARKET=".claude-plugin/marketplace.json"
MANIFEST="plugins/makehardware/.claude-plugin/plugin.json"
BASE="${1:-origin/main}"

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }
skip() { printf '  \033[33m--\033[0m    %s\n' "$1"; }

ver() {  # ver <file> [<ref>] — the version string, or empty
    if [ $# -eq 2 ]; then
        git show "$2:$1" 2>/dev/null | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1
    else
        sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
    fi
}

echo "Plugin version"
echo

# 1. The two manifests must agree, always — nothing to compare against needed.
m=$(ver "${MARKET}")
n=$(ver "${MANIFEST}")
if [ -z "${m}" ] || [ -z "${n}" ]; then
    fail "could not read a version from ${MARKET} or ${MANIFEST}"
elif [ "${m}" = "${n}" ]; then
    pass "marketplace and manifest agree (${m})"
else
    fail "version drift: ${MARKET} says ${m}, ${MANIFEST} says ${n}"
fi

if ! [[ ${m} =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
    fail "'${m}' is not a semver-shaped version"
else
    pass "version is semver-shaped"
fi

# 2. If the plugin changed since the base, the version must have changed too.
if ! git rev-parse --verify --quiet "${BASE}" >/dev/null; then
    skip "no ${BASE} to compare against — skipping the bump check"
    echo
    [ "${fails}" -eq 0 ] && echo "all checks passed" || echo "${fails} check(s) failed"
    [ "${fails}" -eq 0 ]
    exit $?
fi

# Ignore the manifests themselves: bumping the version is not a plugin change.
changed=$(git diff --name-only "${BASE}"...HEAD -- plugins/makehardware/ \
          | grep -v '\.claude-plugin/' | grep -v '__pycache__' || true)

if [ -z "${changed}" ]; then
    skip "no plugin changes against ${BASE} — nothing to bump for"
else
    was=$(ver "${MANIFEST}" "${BASE}")
    count=$(printf '%s\n' "${changed}" | wc -l | tr -d ' ')
    if [ -z "${was}" ]; then
        skip "no version on ${BASE} to compare — treating as a first release"
    elif [ "${was}" != "${n}" ]; then
        pass "${count} plugin file(s) changed and the version moved ${was} -> ${n}"
    else
        fail "${count} plugin file(s) changed but the version is still ${n}"
        printf '        %s\n' ${changed} | head -8
        echo
        echo "        Bump it in BOTH files, or a client that already has"
        echo "        ${n} will treat the update as nothing to do and keep"
        echo "        running the old code:"
        echo "          ${MARKET}"
        echo "          ${MANIFEST}"
    fi
fi

echo
if [ "${fails}" -eq 0 ]; then echo "all checks passed"; else echo "${fails} check(s) failed"; fi
[ "${fails}" -eq 0 ]
