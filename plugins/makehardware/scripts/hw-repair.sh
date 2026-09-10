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
#   hw-repair kicad      install ki-stack and clear the Konnect leftovers
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

KI_STACK_REPO="${KI_STACK_REPO:-https://github.com/Milind220/ki-stack}"
KI_STACK_REV="${KI_STACK_REV:-d5f5d0103e4b2a5572f724fe90cb49dc4f131d37}"
KI_STACK_ROOT="${KI_STACK_ROOT:-/opt/ki-stack}"
KI_STACK_PACK="${KI_STACK_ROOT}/skills/ki-stack"
SKILL_DIR="${MH_SKILL_DIR:-/root/.claude/skills}"
AGENT_DIR="${MH_AGENT_DIR:-/root/.claude/agents}"

# What `konnect init` used to write. All of it instructs an agent to route
# KiCad changes through MCP tools this plugin no longer registers.
KONNECT_SKILLS="konnect kicad-schematic kicad-pcb kicad-review kicad-library kicad-manufacture"
KONNECT_AGENTS="kicad-schematic-build-agent kicad-design-review-agent"
KI_STACK_SKILLS="ki-stack-orient ki-stack-render ki-stack-live ki-stack-file-surgery ki-stack-verify ki-stack-pcb ki-stack-schematic ki-stack-symbols ki-stack-footprints"

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
# kicad — ki-stack in, Konnect leftovers out
#
# 0.7.0 replaced Konnect with ki-stack. An environment built before that still
# carries Konnect's six skills and two agents in its snapshot, and they are
# worse than absent: they tell the agent that every `.kicad_*` change MUST go
# through MCP tools that are no longer registered, so it reads a missing tool
# as a broken environment and stops, rather than reaching for kicad-cli or the
# IPC bindings that are right there.
# --------------------------------------------------------------------------
_konnect_leftovers() {
    local n
    for n in ${KONNECT_SKILLS}; do
        [ -e "${SKILL_DIR}/${n}" ] && return 0
    done
    for n in ${KONNECT_AGENTS}; do
        [ -e "${AGENT_DIR}/${n}.md" ] && return 0
    done
    return 1
}

_kistack_installed() { [ -d "${KI_STACK_PACK}" ]; }

repair_kicad() {
    _need_root
    if ! _kistack_installed; then
        _say "kicad: cloning ki-stack ${KI_STACK_REV:0:7}..."
        rm -rf "${KI_STACK_ROOT}"
        # Full clone, not shallow: a shallow clone cannot check out a pinned
        # revision, and the pin is the point.
        git clone -q "${KI_STACK_REPO}" "${KI_STACK_ROOT}" >>"${LOG}" 2>&1 \
            || _die "could not clone ${KI_STACK_REPO}"
        git -C "${KI_STACK_ROOT}" checkout -q "${KI_STACK_REV}" >>"${LOG}" 2>&1 \
            || _die "could not check out ${KI_STACK_REV}"
        [ -d "${KI_STACK_PACK}" ] || _die "${KI_STACK_PACK} missing in that revision"
    fi

    chmod +x "${KI_STACK_PACK}"/bin/* 2>>"${LOG}"
    local helper name
    for helper in "${KI_STACK_PACK}"/bin/*; do
        [ -f "${helper}" ] || continue
        name=$(basename "${helper}")
        # rm -f first: `cat >` follows a symlink, and a leftover symlink here
        # would send the wrapper straight through into the upstream script.
        rm -f "/usr/local/bin/${name}"
        cat > "/usr/local/bin/${name}" <<EOB
#!/usr/bin/env bash
exec "${helper}" "\$@"
EOB
        chmod +x "/usr/local/bin/${name}"
    done

    mkdir -p "${SKILL_DIR}"
    local sk
    for sk in ${KI_STACK_SKILLS}; do
        [ -d "${KI_STACK_PACK}/${sk}" ] || _die "skill ${sk} absent from ${KI_STACK_REV}"
        rm -rf "${SKILL_DIR:?}/${sk}"
        ln -s "${KI_STACK_PACK}/${sk}" "${SKILL_DIR}/${sk}"
    done
    grep -q 'KI_STACK_DIR' /root/.bashrc 2>/dev/null || \
        printf 'export KI_STACK_DIR=%s\n' "${KI_STACK_PACK}" >> /root/.bashrc
    _say "kicad: ki-stack $("${KI_STACK_PACK}/bin/ki-stack-version" 2>/dev/null || echo '?') — 9 skills installed"

    if _konnect_leftovers; then
        local n removed=0
        for n in ${KONNECT_SKILLS}; do
            [ -e "${SKILL_DIR}/${n}" ] && { rm -rf "${SKILL_DIR:?}/${n}"; removed=$((removed+1)); }
        done
        for n in ${KONNECT_AGENTS}; do
            [ -e "${AGENT_DIR}/${n}.md" ] && { rm -f "${AGENT_DIR}/${n}.md"; removed=$((removed+1)); }
        done
        _say "kicad: removed ${removed} stale Konnect skill(s)/agent(s)"
    fi
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
        _say "  MISSING   ki-stack   hw-repair kicad     (KiCad skills)"
    elif _konnect_leftovers; then
        _say "  STALE     konnect    hw-repair kicad     (leftover skills/agents)"
    else
        _say "  ok        ki-stack   installed, no Konnect leftovers"
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
