#!/usr/bin/env bash
# MakeHardware — Claude Code cloud environment setup script.
#
# Paste this into the "Setup script" field of your cloud environment.
#
# Design constraints this script is written around (see docs/01-environment.md):
#   * Runs as root on Ubuntu 24.04, once, before Claude Code launches.
#   * MUST exit 0. A non-zero exit makes every session in the environment
#     fail to start, so each component records its own status instead of
#     aborting the run.
#   * Should finish in ~5 minutes so the filesystem snapshot can be cached.
#     Independent phases therefore run concurrently.
#   * Only the filesystem is snapshotted. Processes started here do NOT
#     survive; anything that must run per-session belongs in
#     scripts/session-start.sh (wired up as a SessionStart hook).
#   * The script can be killed at the budget without warning. Nothing that a
#     session needs may therefore live only at the end: the helper commands
#     are written before the long phases, status.json is rewritten after every
#     phase, and the tail runs from an EXIT/TERM trap.
#
# Every component writes PASS/FAIL/SKIP into /opt/makehardware/status.json.
# Run `hw-doctor` inside a session to see the result.

set -uo pipefail   # deliberately NOT -e: see "MUST exit 0" above.

export DEBIAN_FRONTEND=noninteractive
export PATH="/root/.cargo/bin:${PATH}"

PREFIX=/opt/makehardware
VENV=/opt/hw-py
STATUS="${PREFIX}/status.json"
LOGDIR="${PREFIX}/logs"
mkdir -p "${PREFIX}" "${LOGDIR}"

# Opt-in extras. Both need domains that the Trusted allowlist does not cover;
# see env/allowed-domains.txt.
: "${MH_ENABLE_KICAD:=${MH_ENABLE_KONNECT:-1}}"  # KiCad 10 + ki-stack (needs ppa.launchpadcontent.net)
# MH_ENABLE_KONNECT was this switch's name until 0.7.0 and is still honoured
# above, so an environment carrying the old variable keeps working rather than
# silently losing KiCad.
: "${MH_ENABLE_LTSPICE:=0}"   # LTspice under Wine      (needs *.analog.com)

# The MakeHardware plugin itself — skills, commands, bin/ and the MCP servers.
# Installed at user scope at build time; see phase_plugin for why the project
# repo's own settings.json cannot do this on its own in a cloud session.
: "${MH_ENABLE_PLUGIN:=1}"
: "${MH_PLUGIN_SOURCE:=Harwasch/MakeHardware}"   # anything `claude plugin marketplace add` takes
: "${MH_PLUGIN_NAME:=makehardware}"
: "${MH_PLUGIN_ID:=makehardware@makehardware}"

# Magnetics and field simulation — Elmer, FastHenry, GetDP. Everything it
# needs is on archive.ubuntu.com, github.com or ppa.launchpadcontent.net —
# the last of which the KiCad phase already requires, so enabling magnetics
# costs no allowlist entry that KiCad has not already spent.
# Measured: ~3 minutes, and it runs concurrently with kicad and python.
: "${MH_ENABLE_MAGNETICS:=1}"
# Elmer comes from the upstream elmer-csc PPA — the same host as the KiCad
# PPA above, so it costs no new allowlist entry.
#
# It used to be pulled from a prebuilt tarball published as a release asset on
# this repository. That asset never existed. The URL 404'd on every build in
# every environment from the day it was written, phase_magnetics degraded every
# time, and because a DEGRADED phase still exits 0 the environment came up
# looking healthy with no ElmerSolver in it. Nobody was reading the log the one
# line naming the 404 was written to. Do not reintroduce a private asset here:
# the PPA is upstream's own build, it is reproducible from this file alone, and
# apt tells you loudly when it cannot fetch it.
: "${MH_ELMER_PPA:=https://ppa.launchpadcontent.net/elmer-csc-ubuntu/elmer-csc-ppa/ubuntu/}"
: "${MH_ELMER_SUITE:=noble}"
: "${MH_ELMER_PACKAGE:=elmerfem-csc}"
# "Launchpad PPA for Elmer CSC ubuntu packaging". Pinned so the archive is
# authenticated against a key we named rather than whatever the keyserver hands
# back for a search string.
MH_ELMER_PPA_FINGERPRINT="1FE4A88ACFEE8388A409F23A89358ABF9FB7E178"

# ki-stack — the KiCad skill pack. Skills, not an MCP server, so this is a
# pinned clone rather than a binary install. Pin the revision: the skills are
# instructions an agent follows, and an unpinned clone means the guidance can
# change under a project between one session and the next.
: "${KI_STACK_REPO:=https://github.com/Milind220/ki-stack}"
: "${KI_STACK_REV:=d5f5d0103e4b2a5572f724fe90cb49dc4f131d37}"
: "${KI_STACK_DIR:=/opt/ki-stack/skills/ki-stack}"

# KiCad PPA signing key. Pinned so we never depend on add-apt-repository.
KICAD_PPA_FINGERPRINT="FDA854F61C4D0D9572BB95E5245D5502FAD7A805"
KICAD_PPA_SERIES="noble"


T0=$(date +%s)
SIM_DEFAULT=ngspice
LTSPICE_PATH=""
BUILD_COMPLETE=false
FINALIZED=0

echo ":: MakeHardware environment build starting at $(date -Is)"

# --------------------------------------------------------------------------
# status helpers
#
# status.json is rewritten after every phase, not once at the end. A build cut
# short at the time budget then still leaves a readable diagnosis behind —
# which is the difference between `hw-doctor` telling you what failed and a
# session with no toolchain and no explanation.
# --------------------------------------------------------------------------
: > "${PREFIX}/.status.tsv"

_write_status() {
    local now tmp
    now=$(date +%s)
    tmp=$(mktemp "${STATUS}.XXXXXX") || return 0
    {
        echo '{'
        echo "  \"built_at\": \"$(date -Is)\","
        echo "  \"build_seconds\": $((now - T0)),"
        echo "  \"complete\": ${BUILD_COMPLETE},"
        echo "  \"simulator_default\": \"${SIM_DEFAULT}\","
        echo '  "components": {'
        local first=1 name state detail
        while IFS=$'\t' read -r name state detail; do
            [ -z "${name:-}" ] && continue
            [ ${first} -eq 1 ] || echo ','
            first=0
            printf '    "%s": {"state": "%s", "detail": "%s"}' \
                "${name}" "${state}" "$(printf '%s' "${detail}" | sed 's/"/\\"/g')"
        done < "${PREFIX}/.status.tsv"
        echo
        echo '  }'
        echo '}'
    } > "${tmp}"
    mv -f "${tmp}" "${STATUS}"
}

# Phases record their result from background subshells, so both the append and
# the regeneration that reads the file back run under one lock.
_st() {
    (
        flock 9
        printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" >> "${PREFIX}/.status.tsv"
        _write_status
    ) 9>/var/lock/mh-status.lock
}

# Phases run concurrently but dpkg is a single-writer database, so every
# apt-get call is serialised behind one lock. Without this, an enabled LTspice
# phase and the KiCad phase race and one of them dies on the dpkg lock.
_apt() { flock /var/lock/mh-apt.lock apt-get "$@"; }

# ==========================================================================
# Phase 1 — base OS packages (measured ~25 s)
#
# NOTE: `add-apt-repository` is NEVER used. This image points /usr/bin/python3
# at Python 3.11 via update-alternatives, but Ubuntu 24.04's python3-apt only
# ships apt_pkg.cpython-312-*.so, so add-apt-repository dies with
# "ModuleNotFoundError: No module named 'apt_pkg'". We write the sources file
# and keyring by hand instead, which has no Python dependency at all.
# ==========================================================================
phase_base() {
    # poppler-utils is not optional. The house rule is "never take a number
    # from memory when a datasheet exists", and WebFetch cannot read most
    # datasheet PDFs — it comes back saying the specifications are "embedded
    # within the compressed PDF content stream". pdftotext/pdftoppm are the
    # fallback, and the package is not in this image by default.
    #
    # Nothing here needs a compiler toolchain any more: Konnect was the only
    # thing that was ever built from source, and ki-stack replaced it.
    local build_deps=()

    _apt update -qq
    _apt install -y --no-install-recommends \
        ca-certificates curl wget unzip jq git xz-utils \
        xvfb xauth x11-utils x11-xserver-utils \
        libgl1-mesa-dri libglu1-mesa libegl1 fonts-dejavu-core \
        ngspice \
        gmsh calculix-ccx \
        graphviz \
        poppler-utils \
        "${build_deps[@]}" \
        >"${LOGDIR}/base.log" 2>&1
}

# ==========================================================================
# Phase 2 — Python CAD/analysis environment (measured ~10 s with uv)
#
# uv is pre-installed on the image and is ~20x faster than pip here.
# Python 3.12 is chosen because cadquery-ocp (build123d's OCCT binding)
# publishes cp312 manylinux x86_64 wheels; 3.11 works too, 3.13+ is riskier.
#
# kicad-python (import name `kipy`) is the KiCad team's own bindings for the
# IPC API, and since 0.7.0 it is the live action space rather than an escape
# hatch: `ki-stack-live` drives it directly. It is not optional. PyPI is in the
# proxy's no_proxy list, so it is also the one KiCad automation path in this
# environment that depends on nothing GitHub-side.
#
# Two failure modes are designed around here, both of which cost real time:
#
#   1. ONE `uv pip install` FOR EVERYTHING IS ONE FUSE FOR EVERYTHING. A
#      metadata timeout on pandas took down the whole phase and left the venv
#      empty, and hw-doctor then reported strictdoc, pyyaml, build123d and
#      both MCP servers as five separate failures from one network hiccup.
#      The groups below are ordered by how much depends on them: the
#      requirements and planning gates come first and in their own
#      transaction, so a flaky plotting dependency cannot take them out.
#
#   2. build123d-mcp AND ltspice-mcp CANNOT SHARE A VENV. build123d-mcp
#      requires mcp>=2,<3; ltspice-mcp pins mcp[cli]>=1.27,<2. Whichever
#      resolves last wins and the other dies at import, so one of the two MCP
#      servers fails no matter what — which reads as a broken install rather
#      than a dependency conflict. They are separate processes and share
#      nothing but the interpreter, so each gets its own venv and its console
#      script is symlinked back onto PATH.
# ==========================================================================
VENV_B123D=/opt/hw-py-b123d       # build123d-mcp: needs mcp 2.x
VENV_SPICE=/opt/hw-py-spice       # ltspice-mcp:   needs mcp 1.x

_uvpip() {  # _uvpip <venv> <label> <package...>
    local venv=$1 label=$2; shift 2
    if VIRTUAL_ENV="${venv}" uv pip install "$@" >>"${LOGDIR}/python.log" 2>&1; then
        return 0
    fi
    echo "!! python group '${label}' failed: $*" >>"${LOGDIR}/python.log"
    return 1
}

phase_python() {
    export UV_PYTHON_INSTALL_DIR=/opt/uv-python
    : > "${LOGDIR}/python.log"
    uv venv --python 3.12 "${VENV}" >>"${LOGDIR}/python.log" 2>&1 || return 1

    local degraded=0

    # Essential. The requirements gate, the planning gate, the review gate and
    # every script in the plugin's scripts/ directory need exactly these. If
    # this group fails the phase has failed; nothing else is worth reporting.
    _uvpip "${VENV}" essential strictdoc pyyaml || return 1

    # Datasheet extraction. Small, and the "never take a number from memory"
    # rule depends on it, so it goes early and on its own.
    _uvpip "${VENV}" pdf pypdf || degraded=1

    # CAD and numerics. build123d pulls cadquery-ocp, which is a ~400 MB
    # wheel — by far the most likely thing here to time out, and the reason it
    # is not in the same transaction as anything else.
    _uvpip "${VENV}" cad build123d || degraded=1
    _uvpip "${VENV}" numerics numpy scipy matplotlib || degraded=1
    _uvpip "${VENV}" mesh gmsh meshio || degraded=1

    # kicad-python is the scripted-PCB escape hatch when no KiCad is running.
    _uvpip "${VENV}" kicad kicad-python || degraded=1

    # The two MCP servers, each isolated (see the header).
    for pair in "${VENV_B123D}:build123d-mcp" "${VENV_SPICE}:ltspice-mcp"; do
        local venv=${pair%%:*} pkg=${pair#*:}
        if uv venv --python 3.12 "${venv}" >>"${LOGDIR}/python.log" 2>&1 \
           && _uvpip "${venv}" "${pkg}" "${pkg}"; then
            [ -x "${venv}/bin/${pkg}" ] && ln -sf "${venv}/bin/${pkg}" "${VENV}/bin/${pkg}"
        else
            degraded=1
        fi
    done

    # Expose the console scripts without requiring a venv on PATH.
    for b in strictdoc; do
        [ -x "${VENV}/bin/${b}" ] && ln -sf "${VENV}/bin/${b}" "/usr/local/bin/${b}"
    done
    for pair in "${VENV_B123D}:build123d-mcp" "${VENV_SPICE}:ltspice-mcp"; do
        local venv=${pair%%:*} pkg=${pair#*:}
        [ -x "${venv}/bin/${pkg}" ] && ln -sf "${venv}/bin/${pkg}" "/usr/local/bin/${pkg}"
    done

    "${VENV}/bin/python" -c "
from build123d import Box
b = Box(10, 20, 30)
assert abs(b.volume - 6000.0) < 1e-6, b.volume
" >>"${LOGDIR}/python.log" 2>&1 || degraded=1

    # 2 is DEGRADED in run(): the essential group landed, so the session is
    # usable and hw-doctor will name what is missing.
    [ "${degraded}" = 1 ] && return 2
    return 0
}

# ==========================================================================
# Phase 3 — KiCad 10 from the official PPA
#
# Ubuntu 24.04 universe only carries KiCad 7.0.11, which has no IPC API and no
# `kicad-cli` worth the name, so neither half of ki-stack works against it.
# KiCad 10 must come from the PPA.
#
# IMPORTANT: PPA content is served from ppa.launchpadcontent.net, which is NOT
# in the default Trusted allowlist (that list still names the retired
# ppa.launchpad.net). Without a Custom allowlist entry, `apt-get update` only
# *warns* and `apt-get install kicad` then silently installs KiCad 7 from
# universe. We therefore pin the PPA with an explicit apt preference and
# verify the installed major version afterwards.
# ==========================================================================
phase_kicad() {
    mkdir -p /etc/apt/keyrings
    # --batch --yes --no-tty, or gpg prompts before overwriting an existing
    # keyring and dies on /dev/tty when the build has no controlling terminal.
    # Only bites on a re-run over a warm layer, which is exactly when you least
    # want the KiCad phase to fail.
    curl -fsSL --max-time 60 --retry 3 --retry-delay 2 \
        "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${KICAD_PPA_FINGERPRINT}" \
        | gpg --batch --yes --no-tty --dearmor \
              -o /etc/apt/keyrings/kicad-ppa.gpg 2>"${LOGDIR}/kicad.log" || return 1

    cat > /etc/apt/sources.list.d/kicad.sources <<EOF
Types: deb
URIs: https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/
Suites: ${KICAD_PPA_SERIES}
Components: main
Signed-By: /etc/apt/keyrings/kicad-ppa.gpg
EOF

    # Refuse to fall back to the universe build of KiCad.
    cat > /etc/apt/preferences.d/99-kicad-ppa <<'EOF'
Package: kicad kicad-* libkicad*
Pin: release o=LP-PPA-kicad-kicad-10.0-releases
Pin-Priority: 1001
EOF

    # apt-get update exits 0 even when a repo 403s, so check explicitly.
    #
    # Deliberately NOT `apt-cache policy kicad | grep -q ...`. `grep -q` exits
    # at the first match, apt-cache then dies of SIGPIPE, and `set -o pipefail`
    # reports the whole pipeline as 141 — a *successful* match read as a
    # failure. That is what made this phase announce "PPA unreachable" on a
    # build where the PPA was reachable and the index already fetched, and it
    # sent the diagnosis off to the allowlist for a bug that was pure shell.
    # Capture, then match, so there is no pipe to break.
    local attempt policy
    for attempt in 1 2 3; do
        _apt update -qq >>"${LOGDIR}/kicad.log" 2>&1
        policy="$(apt-cache policy kicad 2>/dev/null)"
        case "${policy}" in *kicad-10.0-releases*) break ;; esac
        {
            echo "attempt ${attempt}: kicad-10.0-releases absent from apt policy; saw:"
            echo "${policy}"
        } >>"${LOGDIR}/kicad.log"
        sleep $((attempt * 3))
    done

    case "${policy}" in
        *kicad-10.0-releases*) ;;
        *)  echo "KiCad 10 PPA not visible to apt after 3 attempts. If the policy" \
                 "output above lists only the universe version, check that" \
                 "ppa.launchpadcontent.net is reachable." >>"${LOGDIR}/kicad.log"
            return 2 ;;
    esac

    # --no-install-recommends keeps kicad-library-packages3d (~2 GB of 3D
    # models) out of the image; symbols and footprints are what we need.
    _apt install -y --no-install-recommends \
        kicad kicad-symbols kicad-footprints kicad-templates \
        >>"${LOGDIR}/kicad.log" 2>&1 || return 1

    kicad-cli version >>"${LOGDIR}/kicad.log" 2>&1 || return 1
    case "$(kicad-cli version 2>/dev/null)" in
        10.*) return 0 ;;
        *)    echo "wrong KiCad major: $(kicad-cli version 2>&1)" >>"${LOGDIR}/kicad.log"
              return 2 ;;
    esac
}

# ==========================================================================
# Phase 4 — ki-stack (KiCad skill pack, measured ~5 s)
#
# ki-stack is skills, not a server. There is no binary to install and no
# process to start: the agent gets a set of SKILL.md files teaching it to drive
# `kicad-python` (live IPC), `kicad-cli` (render, export, DRC, ERC) and
# `kiutils-rs` (structured offline file edits) directly.
#
# This replaced Konnect in 0.7.0. Konnect was an MCP server exposing 214 tools
# over the same IPC API; the swap trades a fixed tool surface for the agent
# writing code against the substrate, which is what these files already assume
# everywhere else — `kicad-cli` has no authoring verb, so *something* has to
# drive the IPC, and a skill that teaches it costs no context until it loads.
#
# Pinned to a revision, deliberately. These are instructions an agent follows,
# so an unpinned clone means the guidance under a project can change between
# one session and the next with nothing in the repo recording it.
#
# The skills are symlinked into ~/.claude/skills rather than copied: the clone
# is the single source, `ki-stack-version` reports the real revision, and an
# update is one `git -C /opt/ki-stack fetch`.
# ==========================================================================
phase_kistack() {
    local log="${LOGDIR}/kistack.log" root=/opt/ki-stack
    : > "${log}"
    echo ":: ki-stack ${KI_STACK_REV} from ${KI_STACK_REPO}" >>"${log}"

    rm -rf "${root}"
    # Not --depth 1: a shallow clone cannot check out an arbitrary revision,
    # and the pin is the point. The repository is small enough that a full
    # clone is under a second.
    git clone -q "${KI_STACK_REPO}" "${root}" >>"${log}" 2>&1 || return 1
    git -C "${root}" checkout -q "${KI_STACK_REV}" >>"${log}" 2>&1 || return 1

    [ -d "${KI_STACK_DIR}" ] || {
        echo "!! ${KI_STACK_DIR} missing — the pack moved in the pinned revision" \
            >>"${log}"
        return 1
    }

    # Its helpers are what the skills actually invoke. The skills find them via
    # $KI_STACK_DIR; these wrappers are so a human can type `kicad-render`.
    #
    # Wrappers, NOT symlinks. Seven of these scripts locate the pack with
    # `dirname "${0}"/../../..`, which under a symlink in /usr/local/bin
    # resolves to `/` — `ki-stack-version` then reports "VERSION file not
    # found" and `kicad-render` looks for its siblings in the wrong place. A
    # wrapper that execs the real path has no such problem.
    chmod +x "${KI_STACK_DIR}"/bin/* 2>>"${log}"
    local helper name
    for helper in "${KI_STACK_DIR}"/bin/*; do
        [ -f "${helper}" ] || continue
        name=$(basename "${helper}")
        # rm -f FIRST. A previous install left a symlink at this path, and
        # `cat >` follows a symlink: without this, the wrapper is written
        # *through* the link and overwrites the upstream script in the clone
        # with an exec of itself — an infinite loop that hangs the build with
        # no error. Found the hard way.
        rm -f "/usr/local/bin/${name}"
        cat > "/usr/local/bin/${name}" <<EOB
#!/usr/bin/env bash
# Wrapper for ki-stack's ${name}. The pack lives at ${KI_STACK_DIR}.
exec "${helper}" "\$@"
EOB
        chmod +x "/usr/local/bin/${name}"
    done

    # Symlinked into the user skill directory, which is part of the snapshot,
    # so every session sees them.
    local skills=/root/.claude/skills sk
    mkdir -p "${skills}"
    for sk in ki-stack-orient ki-stack-render ki-stack-live \
              ki-stack-file-surgery ki-stack-verify \
              ki-stack-pcb ki-stack-schematic ki-stack-symbols \
              ki-stack-footprints
    do
        [ -d "${KI_STACK_DIR}/${sk}" ] || {
            echo "!! skill ${sk} absent from the pinned revision" >>"${log}"
            return 2
        }
        rm -rf "${skills:?}/${sk}"
        ln -s "${KI_STACK_DIR}/${sk}" "${skills}/${sk}" || return 1
    done

    # KI_STACK_DIR is how every skill locates its own bin/ and references/.
    # Without it they fall back to a relative `skills/ki-stack`, which resolves
    # against the *project* directory and finds nothing.
    grep -q 'KI_STACK_DIR' /root/.bashrc 2>/dev/null || cat >> /root/.bashrc <<EOB
export KI_STACK_DIR=${KI_STACK_DIR}
EOB

    # kicad-python is the live action space; without it ki-stack-live is a
    # document about a thing this environment cannot do. phase_python installs
    # it into the shared venv, so this only confirms it landed.
    "${VENV}/bin/python" -c 'import kipy' >>"${log}" 2>&1 \
        || echo "!! kipy not importable — ki-stack-live will be unavailable" >>"${log}"

    "${KI_STACK_DIR}/bin/ki-stack-version" >>"${log}" 2>&1 || return 2
    return 0
}

# ==========================================================================
# Phase 5 — LTspice under Wine (opt-in, off by default)
#
# Off by default because: ltspice.analog.com is not in the Trusted allowlist,
# Wine + the MSI add ~2 GB and several minutes to the build, and ngspice
# already covers the simulation loop headlessly. Turn it on only when you need
# vendor-encrypted ADI models or .asc schematic editing.
# ==========================================================================
phase_ltspice() {
    _apt install -y --no-install-recommends wine wine64 winbind \
        >"${LOGDIR}/ltspice.log" 2>&1 || return 1
    export WINEPREFIX=/opt/ltspice-wine WINEARCH=win64 WINEDEBUG=-all
    mkdir -p "${WINEPREFIX}"
    xvfb-run -a wineboot -u >>"${LOGDIR}/ltspice.log" 2>&1
    curl -fL --max-time 300 https://ltspice.analog.com/download/latest/LTspice64.msi \
        -o /tmp/LTspice64.msi >>"${LOGDIR}/ltspice.log" 2>&1 || return 2
    xvfb-run -a wine msiexec /i /tmp/LTspice64.msi /qn /norestart \
        >>"${LOGDIR}/ltspice.log" 2>&1
    rm -f /tmp/LTspice64.msi
    chmod -R a+rwX "${WINEPREFIX}"
    local exe
    exe="$(find "${WINEPREFIX}/drive_c" -type f -iname 'LTspice.exe' -print -quit 2>/dev/null)"
    [ -n "${exe}" ] || return 1
    echo "${exe}" > "${PREFIX}/ltspice-path"
}

# ==========================================================================
# Phase 6 — simulator config + helper commands
#
# These are pure heredocs that depend on no phase, so they are written before
# the long ones rather than after. A build that dies at the budget then still
# leaves a session that can start a display and read its own status.
# ==========================================================================
write_sim_config() {
    cat > /etc/ltspice-mcp.toml <<EOF
# ltspice-mcp serves both LTspice and ngspice. ngspice is the default here:
# it runs headless, needs no Wine, and is a first-class backend in this server.
[simulator]
default = "${SIM_DEFAULT}"
$( [ -n "${LTSPICE_PATH}" ] && echo "path = \"${LTSPICE_PATH}\"" )
# "hsa" makes ngspice select the right section out of a sectioned .lib, which
# is how most vendor corner models are shipped.
ngbehavior = "hsa"

[simulation]
max_parallel = 4
timeout = 300.0

[tools]
# Drops the netlist-editing wrappers a capable agent does with plain file
# edits, and keeps simulation lifecycle, .raw parsing and batch orchestration.
profile = "agentic"

[state]
persist_jobs = true
EOF
}

install_helpers() {
    # --- hw-display-start: the Xvfb the GUI tools need --------------------
    cat > /usr/local/bin/hw-display-start <<'EOF'
#!/usr/bin/env bash
# Snapshots capture files, not processes, so the display must be (re)started
# per session. Idempotent.
set -e
if xdpyinfo -display :99 >/dev/null 2>&1; then exit 0; fi
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/hw-xvfb.log 2>&1 &
for _ in $(seq 1 40); do
    xdpyinfo -display :99 >/dev/null 2>&1 && exit 0
    sleep 0.25
done
echo "hw-display-start: Xvfb :99 did not come up" >&2
exit 1
EOF
    chmod +x /usr/local/bin/hw-display-start

    # --- hw-kicad-up: live KiCad for the IPC action space -----------------
    cat > /usr/local/bin/hw-kicad-up <<'EOF'
#!/usr/bin/env bash
# Bring up KiCad with a project open so the kicad-python IPC bindings have
# something to connect to — that is what `ki-stack-live` needs. Only for live
# board work: render, export, ERC/DRC and structured file edits all run
# headless and need none of this.
set -e
hw-display-start
export DISPLAY=:99 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1
if pgrep -x kicad >/dev/null 2>&1; then echo "kicad already running"; exit 0; fi
nohup kicad "$@" >/tmp/hw-kicad.log 2>&1 &
echo "kicad pid $!  (IPC socket: ipc:///tmp/kicad/api.sock)"
EOF
    chmod +x /usr/local/bin/hw-kicad-up

    write_sim_config
}

install_ltspice_helper() {
    cat > /usr/local/bin/hw-ltspice <<EOF
#!/usr/bin/env bash
set -e
hw-display-start
export DISPLAY=:99 WINEPREFIX=/opt/ltspice-wine WINEARCH=win64 WINEDEBUG=-all
exec wine "${LTSPICE_PATH}" "\$@"
EOF
    chmod +x /usr/local/bin/hw-ltspice
}

# ==========================================================================
# Phase 7 — the MakeHardware plugin itself
#
# WHY THIS IS HERE AND NOT LEFT TO THE PROJECT REPO:
#
#   A project repo's .claude/settings.json declares the marketplace in
#   extraKnownMarketplaces and enables the plugin in enabledPlugins. That is
#   necessary but NOT sufficient, and it fails silently in a cloud session:
#
#     1. A marketplace declared by a repo's own files is only registered for a
#        folder you have TRUSTED for plugins. A cloud session has no trust
#        dialog to accept, so the declaration is ignored and the session logs
#        "Skipping orphaned enabledPlugins entry ...: marketplace not
#        registered" — at debug level, where nobody sees it.
#     2. enabledPlugins only ENABLES an already-installed plugin. It never
#        installs one. Registering the marketplace alone still leaves the
#        skills, the commands, the MCP servers and bin/ absent.
#
#   Installing here sidesteps both. This runs as root at build time and writes
#   to /root/.claude, which is part of the snapshot, so the plugin is present
#   and enabled at USER scope in every session regardless of folder trust —
#   the same trick phase_kistack uses for the KiCad skills.
#
#   The GitHub *API* 403s for repos not attached to the session, but `claude
#   plugin marketplace add` clones over HTTPS, and a public repo clone is
#   served at every network level. Verified with a scrubbed environment: no
#   session credentials are needed. Both steps are idempotent and exit 0 when
#   the marketplace or plugin is already there, so a rebuild is a no-op.
# ==========================================================================
phase_plugin() {
    local log="${LOGDIR}/plugin.log" claude_bin
    claude_bin=$(command -v claude 2>/dev/null || true)
    [ -n "${claude_bin}" ] || claude_bin="${CLAUDE_CODE_EXECPATH:-/opt/claude-code/bin/claude}"
    if [ ! -x "${claude_bin}" ]; then
        echo "no claude executable found" >>"${log}" 2>&1
        return 1
    fi

    # `add` on an already-registered marketplace succeeds; `update` is the
    # refresh path for a rebuild whose snapshot already carries the clone.
    "${claude_bin}" plugin marketplace add "${MH_PLUGIN_SOURCE}" >>"${log}" 2>&1 \
        || "${claude_bin}" plugin marketplace update "${MH_PLUGIN_NAME}" >>"${log}" 2>&1 \
        || return 1

    "${claude_bin}" plugin install "${MH_PLUGIN_ID}" >>"${log}" 2>&1 || return 1

    # An install that loads with a bad manifest still reports success, so
    # confirm the plugin actually reached "enabled" rather than trusting rc.
    "${claude_bin}" plugin list 2>>"${log}" | grep -q "enabled" || return 2
}

# ==========================================================================
# Phase 7b — magnetics and field simulation (measured ~3 min)
#
# SPICE cannot tell you an inductance. This phase is what lets a session answer
# "what is L, M, k, Q, R_ac" and "what does the ferrite do" — see the
# hw-magnetics skill for which tool answers which question.
#
# gmsh and calculix-ccx are already installed by phase_base; only the three
# magnetics-specific tools are added here.
#
# Elmer needs ppa.launchpadcontent.net, which is also what KiCad 10 needs and
# is NOT in the default Trusted allowlist — see env/allowed-domains.txt.
# Everything else here is on the Trusted allowlist already.
# ==========================================================================
phase_magnetics() {
    local log="${LOGDIR}/magnetics.log" degraded=0
    : > "${log}"
    echo ":: elmer ${MH_ELMER_PACKAGE} from ${MH_ELMER_PPA} (${MH_ELMER_SUITE})" >>"${log}"

    _apt install -y -q --no-install-recommends \
        getdp libgfortran5 libopenblas0 gfortran >>"${log}" 2>&1 || return 1

    # --- Elmer, from the elmer-csc PPA -----------------------------------
    # Measured ~70 s including its MPI and MUMPS dependencies. The packaged
    # build is self-contained: ElmerSolver finds its own solver modules under
    # /usr/share/elmersolver/lib with no LD_LIBRARY_PATH set, which the tarball
    # this replaced could not do.
    mkdir -p /etc/apt/keyrings
    if curl -fsSL --max-time 60 --retry 3 --retry-delay 2 \
            "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${MH_ELMER_PPA_FINGERPRINT}" \
            2>>"${log}" \
        | gpg --batch --yes --no-tty --dearmor \
              -o /etc/apt/keyrings/elmer-ppa.gpg 2>>"${log}"; then
        cat > /etc/apt/sources.list.d/elmer.sources <<EOF
Types: deb
URIs: ${MH_ELMER_PPA}
Suites: ${MH_ELMER_SUITE}
Components: main
Signed-By: /etc/apt/keyrings/elmer-ppa.gpg
EOF
        # apt-get update exits 0 even when a repo 403s, so ask apt whether it
        # can actually see the package rather than trusting the return code.
        # Captured, then matched: `apt-cache policy | grep -q` would SIGPIPE
        # the writer and pipefail would report a match as a failure — the same
        # trap phase_kicad documents at length.
        local policy
        _apt update -qq >>"${log}" 2>&1
        policy="$(apt-cache policy "${MH_ELMER_PACKAGE}" 2>/dev/null)"
        case "${policy}" in
            *elmer-csc*)
                _apt install -y -q --no-install-recommends "${MH_ELMER_PACKAGE}" \
                    >>"${log}" 2>&1 || degraded=1
                ;;
            *)  echo "!! ${MH_ELMER_PACKAGE} not visible to apt; saw:" >>"${log}"
                echo "${policy}" >>"${log}"
                echo "!! check that ppa.launchpadcontent.net is reachable — the" \
                     "KiCad phase needs the same host" >>"${log}"
                degraded=1
                ;;
        esac
    else
        echo "!! could not fetch the elmer-csc PPA signing key" >>"${log}"
        degraded=1
    fi

    ldconfig
    # Prove it before claiming it. A solver that installs and will not start is
    # the failure this phase existed to have and did not report for months.
    ElmerSolver --version >>"${log}" 2>&1 || degraded=1
    ElmerGrid >>"${log}" 2>&1

    # --- FastHenry2 ------------------------------------------------------
    # 1990s C against GCC >= 10: without -fcommon it dies on
    # "multiple definition of 'timestuff'". Stale objects mask the fix, so
    # the tree is cleaned before the flag goes in.
    if git clone -q --depth 1 https://github.com/ediloren/FastHenry2.git \
            /opt/FastHenry2 >>"${log}" 2>&1; then
        (
            cd /opt/FastHenry2 || exit 1
            find . -name '*.o' -delete
            grep -rl "CFLAGS = -O " --include=Makefile . \
                | xargs -r sed -i 's/^CFLAGS = -O /CFLAGS = -O2 -fcommon /'
            make all && install -m755 bin/fasthenry /usr/local/bin/fasthenry
        ) >>"${log}" 2>&1 || degraded=1
    else
        degraded=1
    fi

    # --- worked .sif files ----------------------------------------------
    # `.sif` is a niche format and the failure mode is a solver that runs
    # happily and reports zero, so the guidance is to copy a working file
    # rather than author one. These are those files.
    git clone -q --depth 1 https://github.com/ElmerCSC/elmer-elmag.git \
        /opt/elmer-elmag >>"${log}" 2>&1 || degraded=1

    command -v fasthenry >/dev/null || return 1
    [ "${degraded}" = 1 ] && return 2
    return 0
}

# ==========================================================================
# Phase 8 — finalize. Runs from a trap, so a kill at the time budget still
# writes the status file and the LTspice wiring instead of leaving neither.
# ==========================================================================
finalize() {   # finalize <complete|interrupted>
    [ "${FINALIZED}" = 1 ] && return 0
    FINALIZED=1
    trap - EXIT TERM INT HUP

    LTSPICE_PATH="$(cat "${PREFIX}/ltspice-path" 2>/dev/null || true)"
    if [ -n "${LTSPICE_PATH}" ]; then
        SIM_DEFAULT=ltspice
        write_sim_config
        install_ltspice_helper
    fi

    if [ "${1:-complete}" = complete ]; then
        BUILD_COMPLETE=true
        # Trim the snapshot. Skipped when interrupted: apt may be mid-run in a
        # background phase, and clearing its lists under it does real damage
        # for a saving that only matters on a build that finished anyway.
        rm -rf /root/.cargo/registry/src /root/.cargo/git 2>/dev/null
        apt-get clean
        rm -rf /var/lib/apt/lists/*
    else
        echo ":: build interrupted — writing status early" >&2
    fi

    _write_status

    echo
    echo ":: MakeHardware environment build finished in $(($(date +%s) - T0))s"
    cat "${STATUS}"
    echo
    echo ":: Run 'hw-doctor' inside a session for a live check."
}

trap 'finalize interrupted; exit 0' TERM INT HUP
trap 'finalize interrupted' EXIT

# ==========================================================================
# Run the phases. Base must land before the rest; the remainder overlap so the
# wall clock is roughly max(kicad, python) rather than their sum.
# ==========================================================================
run() {  # run <name> <fn>
    local name=$1 fn=$2 rc
    "${fn}"; rc=$?
    case ${rc} in
        0) _st "${name}" PASS ;;
        2) _st "${name}" DEGRADED "see ${LOGDIR}/${name}.log" ;;
        *) _st "${name}" FAIL "see ${LOGDIR}/${name}.log" ;;
    esac
}

install_helpers

run base phase_base

run python phase_python &
PID_PY=$!

if [ "${MH_ENABLE_KICAD}" = "1" ]; then
    run kicad phase_kicad &
    PID_KICAD=$!
    run kistack phase_kistack &
    PID_KISTACK=$!
else
    _st kicad SKIP "MH_ENABLE_KICAD=0"
    _st kistack SKIP "MH_ENABLE_KICAD=0"
fi

if [ "${MH_ENABLE_PLUGIN}" = "1" ]; then
    run plugin phase_plugin &
    PID_PLUGIN=$!
else
    _st plugin SKIP "MH_ENABLE_PLUGIN=0 — install it from the project repo instead"
fi

if [ "${MH_ENABLE_MAGNETICS}" = "1" ]; then
    run magnetics phase_magnetics &
    PID_MAG=$!
else
    _st magnetics SKIP "MH_ENABLE_MAGNETICS=0"
fi

if [ "${MH_ENABLE_LTSPICE}" = "1" ]; then
    run ltspice phase_ltspice &
    PID_LT=$!
else
    _st ltspice SKIP "MH_ENABLE_LTSPICE=0 — ngspice is the default simulator"
fi

wait

finalize complete

# Always succeed: a failed component degrades the session, it must not
# prevent the session from starting at all.
exit 0
