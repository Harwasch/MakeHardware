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
#   hw-repair all        everything repairable that is currently missing
#
# Every repair is idempotent and re-verifies the tool afterwards. A repair that
# cannot verify its tool fails loudly rather than reporting success.
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
    _say ""
    _say "Run \`hw-doctor\` for the full picture. A repair here fixes this"
    _say "container only — the environment's snapshot is unchanged, so the next"
    _say "session starts degraded again until env/setup.sh is rebuilt."
}

: > "${LOG}"
case "${1:-}" in
    ""|-h|--help|status) report ;;
    elmer)               repair_elmer ;;
    kicad)               repair_kicad ;;
    all)                 repair_kicad; repair_elmer ;;
    *) _die "unknown repair '$1' — try: elmer, kicad, all" ;;
esac
