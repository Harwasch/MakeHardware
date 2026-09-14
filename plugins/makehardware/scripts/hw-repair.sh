#!/usr/bin/env bash
# hw-repair — install, at run time, a tool the environment build failed to.
#
# The environment is a filesystem snapshot taken once, before any session
# starts. When a phase degrades, every session made from that snapshot is
# missing the tool, and the only clean fix — rebuild the environment — is not
# something an agent mid-task can do or should wait for.
#
# So: this repairs the running container. It does not survive the session, and
# it is not a substitute for fixing env/setup.sh. It is what lets an agent keep
# going instead of reporting "the toolchain is degraded" and stopping, which is
# the wrong answer to a problem it can solve in ninety seconds.
#
#   hw-repair            what is missing and what can be repaired
#   hw-repair elmer      install Elmer (~70 s, needs ppa.launchpadcontent.net)
#   hw-repair kicad      install KiStack and clear out any previous pack
#   hw-repair base       re-install the base OS packages phase_base installs
#   hw-repair python     which Python groups are missing
#   hw-repair python cad re-run one of phase_python's install groups
#   hw-repair all        everything repairable that is currently missing
#
# Every repair is idempotent and re-verifies the tool afterwards. A repair that
# cannot verify its tool fails loudly rather than reporting success.
#
# WHAT A REPAIR CANNOT REACH, and the line is sharp:
#
#   An agent can repair anything consumed by a SUBPROCESS IT SPAWNS — apt
#   packages, Python packages, cloned repos, files in /usr/local/bin. Those
#   work the moment the install finishes.
#
#   It cannot repair anything consumed by the SESSION'S OWN TOOL REGISTRY —
#   MCP servers, skills, slash commands, bin/ on PATH, environment variables.
#   Those are read once when the session starts. Installing build123d-mcp
#   mid-session gives you a working binary and no MCP tools, which looks
#   exactly like a failed repair and is not one. Every repair that lands on
#   that side of the line says "restart the session" and means it.
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

LOG="${TMPDIR:-/tmp}/hw-repair.log"
ELMER_PPA="${MH_ELMER_PPA:-https://ppa.launchpadcontent.net/elmer-csc-ubuntu/elmer-csc-ppa/ubuntu/}"
ELMER_SUITE="${MH_ELMER_SUITE:-noble}"
ELMER_PACKAGE="${MH_ELMER_PACKAGE:-elmerfem-csc}"
ELMER_FINGERPRINT="1FE4A88ACFEE8388A409F23A89358ABF9FB7E178"

KISTACK_REPO="${KISTACK_REPO:-https://github.com/American-Embedded/KiStack}"
KISTACK_REV="${KISTACK_REV:-73ece96e45a3a202f2ca05af32c66dbcefcf9851}"
KISTACK_DIR="${KISTACK_DIR:-/opt/kistack}"
SKILL_DIR="${MH_SKILL_DIR:-/root/.claude/skills}"
AGENT_DIR="${MH_AGENT_DIR:-/root/.claude/agents}"

# Two previous KiCad substrates to clean up after.
#
# Konnect (through 0.6.0) wrote six skills and two agents that route every
# change through MCP tools this plugin no longer registers.
#
# `kicad-schematic` and `kicad-pcb` are on that list AND are two of the names
# KiStack uses, so those two are matched on CONTENT, never on filename —
# deleting them by name would delete the pack that just replaced them. Only
# Konnect's own skills mention Konnect.
KONNECT_ONLY_SKILLS="konnect kicad-review kicad-library kicad-manufacture"
KONNECT_SHARED_NAMES="kicad-schematic kicad-pcb"
KONNECT_AGENTS="kicad-schematic-build-agent kicad-design-review-agent"

# ki-stack (0.7.0 only) prefixes every skill, so its names are unambiguous.
# Its shell helpers were installed as wrappers into /usr/local/bin and point
# into a clone this repair is about to delete.
OLD_KI_STACK_ROOT=/opt/ki-stack
OLD_KI_STACK_HELPERS="ki-stack-version ki-stack-update-check ki-stack-install-opencode kicad-version kicad-project-find kicad-cli-path kicad-python-smoke kicad-render kicad-svg-to-png kicad-drc-json kicad-erc-json kiutils-inspect"

# --------------------------------------------------------------------------
# The two tables that mirror env/setup.sh
#
# setup.sh is pasted into the environment dialog as one self-contained file
# and cannot source anything from this repo; this script ships inside the
# plugin. They are physically unable to share a definition, so they are
# duplicated and `tests/python-groups.sh` greps both and fails when they
# disagree. Hand-syncing is how they drift; checking is the house answer.
#
# Format: <group>:<packages>:<import probe>. Keep the groups, their order and
# their packages identical to phase_python's `_uvpip "${VENV}" ...` lines.
# --------------------------------------------------------------------------
VENV="${MH_VENV:-/opt/hw-py}"
VENV_B123D="${MH_VENV_B123D:-/opt/hw-py-b123d}"
VENV_SPICE="${MH_VENV_SPICE:-/opt/hw-py-spice}"

PY_GROUPS="essential:strictdoc pyyaml:import yaml
pdf:pypdf:import pypdf
cad:build123d:import build123d
numerics:numpy scipy matplotlib:import numpy, scipy, matplotlib
mesh:gmsh meshio:import gmsh, meshio
kicad:kicad-python:import kipy"

# Mirrors phase_base's apt list. Same rule: tests/python-groups.sh checks it.
BASE_PKGS="ca-certificates curl wget unzip jq git xz-utils xvfb xauth x11-utils x11-xserver-utils libgl1-mesa-dri libglu1-mesa libegl1 fonts-dejavu-core ngspice gmsh calculix-ccx graphviz poppler-utils socat"

_have() { command -v "$1" >/dev/null 2>&1; }
_say()  { printf '%s\n' "$*"; }
_die()  { printf 'hw-repair: %s\n' "$*" >&2; printf '  log: %s\n' "${LOG}" >&2; exit 1; }

_need_root() {
    [ "$(id -u)" = 0 ] || _die "must run as root — apt needs it"
}

# --------------------------------------------------------------------------
# elmer
# --------------------------------------------------------------------------
repair_elmer() {
    if _have ElmerSolver; then
        _say "elmer: already installed — $(ElmerSolver --version 2>&1 | head -1)"
        return 0
    fi
    _need_root
    _say "elmer: installing ${ELMER_PACKAGE} from the elmer-csc PPA (~70 s)..."

    mkdir -p /etc/apt/keyrings
    curl -fsSL --max-time 60 --retry 3 --retry-delay 2 \
        "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${ELMER_FINGERPRINT}" \
        2>>"${LOG}" \
      | gpg --batch --yes --no-tty --dearmor -o /etc/apt/keyrings/elmer-ppa.gpg 2>>"${LOG}" \
      || _die "could not fetch the elmer-csc PPA signing key. If this session's
  network access is Custom rather than Full, ppa.launchpadcontent.net must be
  on the allowlist — see env/allowed-domains.txt."

    cat > /etc/apt/sources.list.d/elmer.sources <<EOF
Types: deb
URIs: ${ELMER_PPA}
Suites: ${ELMER_SUITE}
Components: main
Signed-By: /etc/apt/keyrings/elmer-ppa.gpg
EOF

    apt-get update -qq >>"${LOG}" 2>&1
    # apt-get update exits 0 even when the repo 403s, so ask apt what it can
    # see. Captured then matched — never piped into grep -q, which SIGPIPEs the
    # writer and turns a match into a pipeline failure.
    local policy; policy="$(apt-cache policy "${ELMER_PACKAGE}" 2>/dev/null)"
    case "${policy}" in
        *elmer-csc*) ;;
        *) printf '%s\n' "${policy}" >>"${LOG}"
           _die "${ELMER_PACKAGE} is not visible to apt. ppa.launchpadcontent.net
  is probably unreachable from this session — it is the same host KiCad 10
  needs, so check whether kicad-cli is present too." ;;
    esac

    apt-get install -y -q --no-install-recommends "${ELMER_PACKAGE}" >>"${LOG}" 2>&1 \
        || _die "apt could not install ${ELMER_PACKAGE}"
    ldconfig

    _have ElmerSolver || _die "installed, but ElmerSolver is still not on PATH"
    ElmerSolver --version >>"${LOG}" 2>&1 \
        || _die "ElmerSolver is installed but will not start"
    _say "elmer: ok — $(ElmerSolver --version 2>&1 | head -1)"

    # The worked .sif cases. Authoring one from scratch is where the silent
    # zero-result failures come from, so the guidance is to copy a working
    # file — which requires the working files to be here.
    if [ ! -d /opt/elmer-elmag ]; then
        _say "elmer: fetching the elmer-elmag worked cases..."
        git clone -q --depth 1 https://github.com/ElmerCSC/elmer-elmag.git \
            /opt/elmer-elmag >>"${LOG}" 2>&1 \
          || _say "elmer: could not fetch elmer-elmag — the solver still works," \
                  "but author a .sif from scratch at your peril"
    fi
    return 0
}

# --------------------------------------------------------------------------
# kicad — KiStack in, the two previous substrates out
#
# The environment is a snapshot taken once, so a session built before a swap
# still carries the old pack's skills. That is worse than carrying nothing:
# Konnect's skills tell the agent every `.kicad_*` change MUST go through MCP
# tools that are no longer registered, so a missing tool reads as a broken
# environment and the agent stops instead of reaching for `kicad-cli`.
# --------------------------------------------------------------------------
_is_konnect_skill() {   # _is_konnect_skill <dir>
    [ -d "$1" ] || return 1
    grep -qil 'konnect' "$1/SKILL.md" 2>/dev/null
}

_konnect_leftovers() {
    local n
    for n in ${KONNECT_ONLY_SKILLS}; do
        [ -e "${SKILL_DIR}/${n}" ] && return 0
    done
    for n in ${KONNECT_SHARED_NAMES}; do
        _is_konnect_skill "${SKILL_DIR}/${n}" && return 0
    done
    for n in ${KONNECT_AGENTS}; do
        [ -e "${AGENT_DIR}/${n}.md" ] && return 0
    done
    return 1
}

_ki_stack_leftovers() {
    [ -d "${OLD_KI_STACK_ROOT}" ] && return 0
    compgen -G "${SKILL_DIR}/ki-stack-*" >/dev/null 2>&1
}

_kistack_installed() { [ -d "${KISTACK_DIR}/skills" ]; }

repair_kicad() {
    _need_root
    if ! _kistack_installed; then
        _say "kicad: cloning KiStack ${KISTACK_REV:0:7}..."
        rm -rf "${KISTACK_DIR}"
        # Full clone, not shallow: a shallow clone cannot check out a pinned
        # revision, and the pin is the point.
        git clone -q "${KISTACK_REPO}" "${KISTACK_DIR}" >>"${LOG}" 2>&1 \
            || _die "could not clone ${KISTACK_REPO}"
        git -C "${KISTACK_DIR}" checkout -q "${KISTACK_REV}" >>"${LOG}" 2>&1 \
            || _die "could not check out ${KISTACK_REV}"
        [ -d "${KISTACK_DIR}/skills" ] || _die "${KISTACK_DIR}/skills missing in that revision"
    fi

    mkdir -p "${SKILL_DIR}"
    # Linked under each skill's frontmatter name, not its directory name —
    # frontmatter is what the agent sees.
    local src name linked=0
    for src in "${KISTACK_DIR}"/skills/*/; do
        [ -f "${src}SKILL.md" ] || continue
        name=$(sed -n 's/^name:[[:space:]]*//p' "${src}SKILL.md" | head -1)
        [ -n "${name}" ] || name=$(basename "${src}")
        rm -rf "${SKILL_DIR:?}/${name}"
        ln -s "${src%/}" "${SKILL_DIR}/${name}"
        linked=$((linked + 1))
    done
    chmod +x "${KISTACK_DIR}"/skills/export/scripts/*.py 2>>"${LOG}"
    _say "kicad: KiStack ${KISTACK_REV:0:7} — ${linked} skills installed"

    # --- Konnect leftovers -------------------------------------------------
    local n removed=0
    for n in ${KONNECT_ONLY_SKILLS}; do
        [ -e "${SKILL_DIR}/${n}" ] && { rm -rf "${SKILL_DIR:?}/${n}"; removed=$((removed+1)); }
    done
    for n in ${KONNECT_SHARED_NAMES}; do
        # Content, not name: KiStack owns these two names now.
        _is_konnect_skill "${SKILL_DIR}/${n}" \
            && { rm -rf "${SKILL_DIR:?}/${n}"; removed=$((removed+1)); }
    done
    for n in ${KONNECT_AGENTS}; do
        [ -e "${AGENT_DIR}/${n}.md" ] && { rm -f "${AGENT_DIR}/${n}.md"; removed=$((removed+1)); }
    done
    [ "${removed}" -gt 0 ] && _say "kicad: removed ${removed} Konnect leftover(s)"

    # --- ki-stack leftovers (0.7.0 only) -----------------------------------
    local old=0 sk
    for sk in "${SKILL_DIR}"/ki-stack-*; do
        [ -e "${sk}" ] || continue
        rm -rf "${sk}"; old=$((old+1))
    done
    for n in ${OLD_KI_STACK_HELPERS}; do
        # Only ours: a wrapper or symlink pointing into the old clone. Never
        # touch an unrelated binary that happens to share the name.
        if [ -L "/usr/local/bin/${n}" ] || grep -q "${OLD_KI_STACK_ROOT}" \
                "/usr/local/bin/${n}" 2>/dev/null; then
            rm -f "/usr/local/bin/${n}"; old=$((old+1))
        fi
    done
    if [ -d "${OLD_KI_STACK_ROOT}" ]; then rm -rf "${OLD_KI_STACK_ROOT}"; old=$((old+1)); fi
    sed -i '/KI_STACK_DIR/d' /root/.bashrc 2>/dev/null
    [ "${old}" -gt 0 ] && _say "kicad: removed ${old} ki-stack leftover(s) from 0.7.0"

    _say "kicad: restart the session for the skill list to refresh"
    return 0
}

# --------------------------------------------------------------------------
# base OS packages
# --------------------------------------------------------------------------
repair_base() {
    _need_root
    _say "base: installing the phase_base package set..."
    apt-get update -qq >>"${LOG}" 2>&1
    # shellcheck disable=SC2086
    if ! apt-get install -y --no-install-recommends ${BASE_PKGS} >>"${LOG}" 2>&1; then
        _die "apt could not install the base set. See ${LOG}."
    fi
    local missing=""
    for c in ngspice gmsh ccx pdftotext socat; do
        _have "${c}" || missing="${missing} ${c}"
    done
    if [ -n "${missing}" ]; then
        _die "installed, but still missing:${missing}"
    fi
    _say "base: ok — ngspice, gmsh, calculix, poppler-utils and socat all answer"
    return 0
}

# --------------------------------------------------------------------------
# python groups
#
# phase_python installs in named groups precisely so one flaky group cannot
# take out the rest; this re-runs one of them. cadquery-ocp is a ~400 MB wheel
# and by far the most likely thing in the build to time out — and it is MORE
# likely to succeed here than it was at build time, because the five-minute
# snapshot budget does not apply to a session.
# --------------------------------------------------------------------------
_uv_bin() {
    # setup.sh runs with /root/.cargo/bin on PATH; a session does not, so
    # `uv` is routinely absent from PATH in exactly the place this runs.
    local c
    for c in uv /root/.local/bin/uv /root/.cargo/bin/uv /usr/local/bin/uv; do
        if [ "${c}" = uv ]; then _have uv && { command -v uv; return 0; }
        elif [ -x "${c}" ]; then printf '%s\n' "${c}"; return 0; fi
    done
    return 1
}

_py_group_field() {  # _py_group_field <group> <1=pkgs|2=probe>
    printf '%s\n' "${PY_GROUPS}" | while IFS=: read -r g pkgs probe; do
        [ "${g}" = "$1" ] || continue
        [ "$2" = 1 ] && printf '%s\n' "${pkgs}" || printf '%s\n' "${probe}"
    done
}

_py_group_ok() {  # _py_group_ok <group>
    local probe; probe="$(_py_group_field "$1" 2)"
    [ -n "${probe}" ] || return 1
    "${VENV}/bin/python" -c "${probe}" >/dev/null 2>&1
}

repair_python() {
    local group="${1:-}"

    # NEVER recreate the venv here. `uv venv` on an existing /opt/hw-py would
    # throw away a working strictdoc to fix matplotlib, and the caller asked
    # for a repair, not a rebuild.
    if [ ! -x "${VENV}/bin/python" ]; then
        _die "${VENV} has no interpreter in it. That is a bootstrap, not a
  repair — this script will not create the venv, because doing so on a
  partially-good one destroys what still works. Rebuild the environment, or
  run env/bootstrap.sh on a bare container."
    fi

    if [ -z "${group}" ]; then
        _say "python groups in ${VENV}:"
        _say ""
        printf '%s\n' "${PY_GROUPS}" | while IFS=: read -r g pkgs _; do
            if _py_group_ok "${g}"; then
                _say "  ok        ${g}"
            else
                _say "  MISSING   ${g}  hw-repair python ${g}    (${pkgs})"
            fi
        done
        _say ""
        _say "\`hw-repair python all-groups\` re-runs every missing one."
        return 0
    fi

    if [ "${group}" = all-groups ]; then
        local rc=0 g
        for g in $(printf '%s\n' "${PY_GROUPS}" | cut -d: -f1); do
            _py_group_ok "${g}" || { repair_python "${g}" || rc=1; }
        done
        return "${rc}"
    fi

    local pkgs; pkgs="$(_py_group_field "${group}" 1)"
    if [ -z "${pkgs}" ]; then
        _die "unknown python group '${group}' — try: $(printf '%s\n' "${PY_GROUPS}" | cut -d: -f1 | tr '\n' ' ')all-groups"
    fi

    local uv; uv="$(_uv_bin)" || _die "uv is not on PATH and is not in
  /root/.local/bin or /root/.cargo/bin. There is deliberately no pip fallback:
  \`uv venv\` creates a venv WITHOUT pip, so \`${VENV}/bin/python -m pip\` does
  not exist and the error it gives says nothing useful."

    _need_root
    _say "python: installing group '${group}' (${pkgs})..."
    # shellcheck disable=SC2086
    if ! VIRTUAL_ENV="${VENV}" "${uv}" pip install ${pkgs} >>"${LOG}" 2>&1; then
        _die "group '${group}' did not install. See ${LOG}."
    fi

    # Verify by import, not by exit code — a resolver can succeed and leave an
    # import broken, which is the failure hw-doctor's chkpy exists to name.
    if ! _py_group_ok "${group}"; then
        _die "group '${group}' installed but still does not import. That is
  usually two packages fighting over one venv, and reinstalling will not fix
  it — see \`hw-doctor\`."
    fi
    _say "python: ok — group '${group}' imports"

    if [ "${group}" = cad ]; then
        _say ""
        _say "  NOTE: this fixed build123d for scripts and for"
        _say "  ${VENV}/bin/python. It did NOT fix the build123d MCP server,"
        _say "  which lives in ${VENV_B123D} and whose process started with"
        _say "  this session. Restart the session to get its tools back."
    fi
    return 0
}

# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
report() {
    _say "hw-repair — run-time repairs for a degraded environment build"
    _say ""
    if _have ElmerSolver; then
        _say "  ok        elmer      $(ElmerSolver --version 2>&1 | head -1)"
    else
        _say "  MISSING   elmer      hw-repair elmer     (~70 s)"
    fi
    if ! _kistack_installed; then
        _say "  MISSING   kistack    hw-repair kicad     (KiCad skills)"
    elif _konnect_leftovers || _ki_stack_leftovers; then
        _say "  STALE     kicad      hw-repair kicad     (leftovers from a previous pack)"
    else
        _say "  ok        kistack    installed, no leftovers"
    fi
    if [ -x "${VENV}/bin/python" ]; then
        local miss=""
        local g
        for g in $(printf '%s\n' "${PY_GROUPS}" | cut -d: -f1); do
            _py_group_ok "${g}" || miss="${miss} ${g}"
        done
        if [ -n "${miss}" ]; then
            _say "  MISSING   python    hw-repair python all-groups  (${miss# })"
        else
            _say "  ok        python     every install group imports"
        fi
    else
        _say "  MISSING   python     ${VENV} has no interpreter — rebuild, or env/bootstrap.sh"
    fi
    if _have ngspice && _have socat; then
        _say "  ok        base       ngspice and socat present"
    else
        _say "  MISSING   base      hw-repair base      (OS packages)"
    fi
    _say ""
    _say "Run \`hw-doctor\` for the full picture. A repair here fixes this"
    _say "container only — the environment's snapshot is unchanged, so the next"
    _say "session starts degraded again until env/setup.sh is rebuilt."
    _say ""
    _say "And a repair reaches subprocesses, not this session's tool registry."
    _say "MCP servers, skills, commands and environment variables are read once"
    _say "at session start; restart the session after any repair that installs"
    _say "one, or it will look like the repair failed when it did not."
}

: > "${LOG}"
case "${1:-}" in
    ""|-h|--help|status) report ;;
    elmer)               repair_elmer ;;
    kicad)               repair_kicad ;;
    base)                repair_base ;;
    python)              repair_python "${2:-}" ;;
    all)                 repair_kicad; repair_elmer; repair_python all-groups ;;
    bootstrap)
        _die "there is no bootstrap subcommand, and there cannot be: this
  script ships inside the plugin, so a container bare enough to need a
  bootstrap does not have it. Use env/bootstrap.sh from the repo:

    curl -fsSL https://raw.githubusercontent.com/Harwasch/MakeHardware/main/env/bootstrap.sh | bash" ;;
    *) _die "unknown repair '$1' — try: elmer, kicad, base, python, all" ;;
esac
