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
# konnect — the subagents' tool namespace
#
# `konnect init` writes `tools: [mcp__konnect__*]` into its two subagents.
# Under this plugin the server namespaces to mcp__plugin_makehardware_konnect__,
# so that glob matches nothing and both agents launch with no tools at all.
# They do not fail loudly; they come back having "reviewed" a board they never
# opened. Every environment built before this was fixed carries the broken
# files in its snapshot.
# --------------------------------------------------------------------------
KONNECT_AGENT_DIR="${MH_AGENT_DIR:-/root/.claude/agents}"

_konnect_agents_broken() {
    local f
    for f in "${KONNECT_AGENT_DIR}"/kicad-*.md; do
        [ -f "${f}" ] || continue
        grep -q 'mcp__plugin_makehardware_konnect__' "${f}" && continue
        grep -q 'mcp__konnect__' "${f}" && return 0
    done
    return 1
}

repair_konnect() {
    if [ ! -d "${KONNECT_AGENT_DIR}" ]; then
        _say "konnect: no agent directory at ${KONNECT_AGENT_DIR} — nothing to repair"
        return 0
    fi
    if ! _konnect_agents_broken; then
        _say "konnect: agents already resolve to this plugin's tool namespace"
        return 0
    fi
    local f fixed=0
    for f in "${KONNECT_AGENT_DIR}"/kicad-*.md; do
        [ -f "${f}" ] || continue
        grep -q 'mcp__plugin_makehardware_konnect__' "${f}" && continue
        # Both patterns are kept so the file stays correct if Konnect is ever
        # registered directly rather than through the plugin.
        sed -i 's|^\(\s*\)- mcp__konnect__\*$|\1- mcp__plugin_makehardware_konnect__*\n\1- mcp__konnect__*|' "${f}" \
            || _die "could not rewrite ${f}"
        _say "konnect: renamespaced $(basename "${f}")"
        fixed=$((fixed+1))
    done
    [ "${fixed}" -gt 0 ] && _say "konnect: restart the session for the agents to pick this up"
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
    if _konnect_agents_broken; then
        _say "  BROKEN    konnect    hw-repair konnect   (agents have no tools)"
    else
        _say "  ok        konnect    agents resolve to this plugin's tools"
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
    konnect)             repair_konnect ;;
    all)                 repair_konnect; repair_elmer ;;
    *) _die "unknown repair '$1' — try: elmer, konnect, all" ;;
esac
