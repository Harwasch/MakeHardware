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

# A python entry point fails in two completely different ways that look
# identical in a one-line report, and they have opposite fixes:
#
#   not installed   — its install group never landed. Read python.log, rerun
#                     the environment build.
#   import error    — it is installed and its dependencies are wrong, which in
#                     practice means two packages fighting over one venv.
#                     Reinstalling changes nothing; it needs its own venv.
#
# So say which. This is the difference between "the environment is broken" and
# "these two servers cannot share an interpreter".
chkpy() {  # chkpy <label> <path> [args...]
    local label=$1 path=$2; shift 2
    local out rc
    if [ ! -x "${path}" ]; then
        printf '  \033[31mFAIL\033[0m %-22s not installed — its group failed; see %s\n' \
            "${label}" "${PREFIX}/logs/python.log"
        bad=$((bad+1))
        return
    fi
    out=$("${path}" "$@" 2>&1); rc=$?
    if [ ${rc} -eq 0 ]; then
        printf '  \033[32mok\033[0m   %-22s %s\n' "${label}" "$(_firstline "${out}")"
        ok=$((ok+1))
        return
    fi
    local missing
    case ${out} in
        *ModuleNotFoundError*|*ImportError*|*"cannot import name"*)
            missing=$(printf '%s' "${out}" \
                | grep -m1 -oE "(ModuleNotFoundError|ImportError):.*" | cut -c1-52)
            printf '  \033[31mFAIL\033[0m %-22s import error, not a missing binary: %s\n' \
                "${label}" "${missing}"
            printf '       %-22s installed at %s — give it its own venv rather than reinstalling\n' \
                "" "${path}"
            ;;
        *)
            printf '  \033[31mFAIL\033[0m %-22s %s\n' "${label}" "$(_firstline "${out}")"
            ;;
    esac
    bad=$((bad+1))
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
chkpy ltspice-mcp  "${VENV}/bin/ltspice-mcp" --help

echo
echo "Mechanical:"
chk build123d      "${VENV}/bin/python" -c "import build123d;print('build123d',build123d.__version__)"
chkpy build123d-mcp "${VENV}/bin/build123d-mcp" --version
chk gmsh           gmsh --version
chkout calculix    "Version [0-9]" ccx -v

echo
echo "Magnetics & field simulation:"
# ElmerSolver prints its banner and then waits for a solver input file, so it
# is checked on --version alone; ElmerGrid with no arguments prints its usage
# banner and exits non-zero, hence chkout. FastHenry with no input file says
# "Unexpected end of file" and still prints its version.
chkout elmer       "v [0-9]+\.[0-9]" ElmerSolver --version
chkout elmergrid   "Version: [0-9]" ElmerGrid
chkout fasthenry   "FastHenry [0-9]" fasthenry
chk getdp          getdp --version
if [ -d /opt/elmer-elmag ]; then
    printf '  \033[32mok\033[0m   %-22s %s worked cases to copy from\n' \
        "elmer-elmag" "$(find /opt/elmer-elmag -maxdepth 1 -mindepth 1 -type d ! -name '.*' | wc -l)"
    ok=$((ok+1))
else
    printf '  \033[33m--\033[0m   %-22s absent — author a .sif from scratch at your peril\n' \
        "elmer-elmag"
fi

echo
echo "Documentation & datasheets:"
# The house rule is "never take a number from memory when a datasheet exists",
# so a missing PDF text extractor is not a cosmetic gap.
chk pdftotext      pdftotext -v
chk pypdf          "${VENV}/bin/python" -c "import pypdf;print('pypdf',pypdf.__version__)"

echo
echo "Requirements, planning & review:"
chk strictdoc      "${VENV}/bin/strictdoc" version
chk pyyaml         "${VENV}/bin/python" -c "import yaml;print('pyyaml',yaml.__version__)"
chk review-gate    "${VENV}/bin/python" \
    "$(dirname "$(readlink -f "$0")")/review_gate.py" --help
chk review-artifact "${VENV}/bin/python" \
    "$(dirname "$(readlink -f "$0")")/review_artifact.py" --help

echo
echo "Design gates and figures:"
# These are read-only and need no KiCad, no MCP server and nothing outside the
# standard library plus pyyaml — so a failure here is a broken checkout rather
# than a missing tool, and worth saying so.
D="$(dirname "$(readlink -f "$0")")"
chk sch-lint       "${VENV}/bin/python" "${D}/sch_lint.py" --help
chk pcb-lint       "${VENV}/bin/python" "${D}/pcb_lint.py" --help
chk hw-chart       "${VENV}/bin/python" "${D}/charts.py" budget --schema
chk cad-export     "${VENV}/bin/python" "${D}/cad_export.py" --help
if command -v freecadcmd >/dev/null 2>&1 || command -v FreeCADCmd >/dev/null 2>&1; then
    printf '  \033[32mok\033[0m   %-22s .FCStd written here\n' "freecad"; ok=$((ok+1))
else
    printf '  \033[33m--\033[0m   %-22s absent — cad-export writes the macro for you to run\n' \
        "freecad"
fi

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
