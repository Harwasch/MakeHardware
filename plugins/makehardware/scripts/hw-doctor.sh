#!/usr/bin/env bash
# hw-doctor — report what the hardware toolchain can actually do right now.
#
# The setup script never fails the session; it degrades. This is how you find
# out what degraded. Run it whenever a tool behaves unexpectedly.
set -uo pipefail
PREFIX=/opt/makehardware
VENV=/opt/hw-py
ok=0; bad=0

# No `printf ... | grep -q` anywhere below. `grep -q` exits at the first match
# and the writer then dies of SIGPIPE, which `set -o pipefail` reports as a
# failed pipeline — a matched version banner read as a FAIL. A checker that
# lies in that direction is worse than no checker; bash matches natively.
_firstline() { printf '%s' "${1%%$'\n'*}" | cut -c1-58; }

# Some tools report success only in their output. CalculiX `ccx -v` exits 201
# on a perfectly good version banner, and ngspice puts its banner on line 2.
chkout() {  # chkout <label> <expected-regex> <command...>
    local label=$1 want=$2; shift 2
    local out
    out=$("$@" 2>&1)
    if [[ ${out} =~ ${want} ]]; then
        printf '  \033[32mok\033[0m   %-22s %s\n' "${label}" \
            "$(grep -m1 -E "${want}" <<<"${out}" | cut -c1-58)"
        ok=$((ok+1))
    else
        printf '  \033[31mFAIL\033[0m %-22s %s\n' "${label}" "$(_firstline "${out}")"
        bad=$((bad+1))
    fi
}

chk() {  # chk <label> <command...>
    local label=$1; shift
    local out
    if out=$("$@" 2>&1); then
        printf '  \033[32mok\033[0m   %-22s %s\n' "${label}" "$(_firstline "${out}")"
        ok=$((ok+1))
    else
        printf '  \033[31mFAIL\033[0m %-22s %s\n' "${label}" "$(_firstline "${out}")"
        bad=$((bad+1))
    fi
}

echo "MakeHardware environment check"
echo

if [ -f "${PREFIX}/status.json" ]; then
    echo "Build status ($(jq -r '.built_at' "${PREFIX}/status.json" 2>/dev/null), \
$(jq -r '.build_seconds' "${PREFIX}/status.json" 2>/dev/null)s):"
    jq -r '.components | to_entries[] | "  \(.key): \(.value.state) \(.value.detail)"' \
        "${PREFIX}/status.json" 2>/dev/null
    # status.json is rewritten after every phase, so it also exists for builds
    # that were killed at the time budget. Say so — the phases missing from the
    # list above never ran, rather than having failed.
    # Match "false" rather than `.complete // "true"`: jq's alternative
    # operator fires on false as well as null, so `//` would swallow exactly
    # the case being tested for. A status.json predating the flag reports
    # "null" here and correctly says nothing.
    if [ "$(jq -r '.complete' "${PREFIX}/status.json" 2>/dev/null)" = "false" ]; then
        printf '  \033[33m!!\033[0m   build did not finish — any phase absent above never ran\n'
    fi
    echo
else
    echo "  (no ${PREFIX}/status.json — setup script did not run or is older than this repo)"
    echo
fi

echo "Electrical:"
chkout ngspice     "ngspice-[0-9]+" ngspice --version
chk kicad-cli      kicad-cli version
chk konnect        konnect --version
chk ltspice-mcp    "${VENV}/bin/ltspice-mcp" --help

echo
echo "Mechanical:"
chk build123d      "${VENV}/bin/python" -c "import build123d;print('build123d',build123d.__version__)"
chk build123d-mcp  "${VENV}/bin/build123d-mcp" --version
chk gmsh           gmsh --version
chkout calculix    "Version [0-9]" ccx -v

echo
echo "Requirements & planning:"
chk strictdoc      "${VENV}/bin/strictdoc" version
chk pyyaml         "${VENV}/bin/python" -c "import yaml;print('pyyaml',yaml.__version__)"

echo
echo "Display (needed only for live KiCad):"
if xdpyinfo -display :99 >/dev/null 2>&1; then
    printf '  \033[32mok\033[0m   %-22s Xvfb :99 up\n' "display"; ok=$((ok+1))
else
    printf '  \033[33m--\033[0m   %-22s not started (run hw-display-start)\n' "display"
fi

echo
echo "${ok} ok, ${bad} failing"
[ "${bad}" -eq 0 ]
