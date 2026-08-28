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
: "${MH_ENABLE_KONNECT:=1}"   # KiCad 10 + Konnect MCP  (needs ppa.launchpadcontent.net)
: "${MH_ENABLE_LTSPICE:=0}"   # LTspice under Wine      (needs *.analog.com)

# Escape hatch: build Konnect from source instead of installing the upstream
# release binary. Costs ~4 minutes and the protobuf/cmake toolchain, so it is
# off — see phase 4.
: "${MH_KONNECT_FROM_SOURCE:=0}"

# KiCad PPA signing key. Pinned so we never depend on add-apt-repository.
KICAD_PPA_FINGERPRINT="FDA854F61C4D0D9572BB95E5245D5502FAD7A805"
KICAD_PPA_SERIES="noble"

# Konnect release pin. Upstream publishes no checksum file, so this is our own
# hash of the asset, taken once and verified on every build. Bump both together.
KONNECT_VERSION="v0.10.0"
KONNECT_SHA256="955b2f956415825aeb122cade1394b3d63bccfd43c6add079722533daac1b7bc"

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
    # cmake/protobuf are only needed to compile Konnect, which we no longer do
    # by default — see phase 4.
    local build_deps=()
    [ "${MH_KONNECT_FROM_SOURCE}" = "1" ] &&
        build_deps=(cmake pkg-config protobuf-compiler libprotobuf-dev)

    _apt update -qq
    _apt install -y --no-install-recommends \
        ca-certificates curl wget unzip jq git xz-utils \
        xvfb xauth x11-utils x11-xserver-utils \
        libgl1-mesa-dri libglu1-mesa libegl1 fonts-dejavu-core \
        ngspice \
        gmsh calculix-ccx \
        graphviz \
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
# same IPC API Konnect drives. It is here as the escape hatch: PyPI is in the
# proxy's no_proxy list, so it is the one KiCad automation path in this
# environment that depends on nothing GitHub-side.
# ==========================================================================
phase_python() {
    export UV_PYTHON_INSTALL_DIR=/opt/uv-python
    uv venv --python 3.12 "${VENV}" >"${LOGDIR}/python.log" 2>&1 || return 1
    VIRTUAL_ENV="${VENV}" uv pip install \
        build123d build123d-mcp \
        ltspice-mcp \
        kicad-python \
        strictdoc \
        numpy scipy pandas matplotlib \
        gmsh meshio pyyaml \
        >>"${LOGDIR}/python.log" 2>&1 || return 1

    # Expose the console scripts without requiring the venv on PATH.
    for b in build123d-mcp ltspice-mcp strictdoc; do
        [ -x "${VENV}/bin/${b}" ] && ln -sf "${VENV}/bin/${b}" "/usr/local/bin/${b}"
    done
    "${VENV}/bin/python" -c "
from build123d import Box
b = Box(10, 20, 30)
assert abs(b.volume - 6000.0) < 1e-6, b.volume
" >>"${LOGDIR}/python.log" 2>&1
}

# ==========================================================================
# Phase 3 — KiCad 10 from the official PPA
#
# Ubuntu 24.04 universe only carries KiCad 7.0.11, which has no IPC API, so
# Konnect cannot drive it. KiCad 10 must come from the PPA.
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
# Phase 4 — Konnect (KiCad MCP server, Rust)
#
# Installed from the upstream release binary, which takes seconds. This used to
# be a ~4 minute source build on the belief that the proxy 403s release assets.
# It does not: the GitHub *API* and the release *web pages* are scoped to
# repositories attached to the session, but the asset path itself is served.
#
#   https://api.github.com/repos/mixelpixx/Konnect/releases   -> 403
#   https://github.com/mixelpixx/Konnect/releases/latest      -> 403
#   .../releases/download/v0.10.0/konnect-…-linux-gnu.tar.gz  -> 200
#
# So `gh release download` and anything API-driven still fails here; a plain
# curl of the asset does not. The binary needs glibc 2.39, which is exactly
# what Ubuntu 24.04 ships, and carries its skills and agents inside itself, so
# the source checkout is not needed for those either.
#
# Set MH_KONNECT_FROM_SOURCE=1 to go back to building — kept working because
# it is the fallback if upstream ever stops publishing a Linux asset.
# ==========================================================================
konnect_from_release() {
    local url tgz
    tgz=/tmp/konnect.tar.gz
    url="https://github.com/mixelpixx/Konnect/releases/download/${KONNECT_VERSION}/konnect-${KONNECT_VERSION}-x86_64-unknown-linux-gnu.tar.gz"

    rm -f "${tgz}"
    curl -fL --max-time 180 --retry 3 --retry-delay 2 -o "${tgz}" "${url}" \
        >"${LOGDIR}/konnect.log" 2>&1 || return 2

    # Upstream ships no checksums file, so this is our own pin. A mismatch is a
    # hard failure, not a degrade: it means the asset is not what we vetted.
    echo "${KONNECT_SHA256}  ${tgz}" | sha256sum -c - \
        >>"${LOGDIR}/konnect.log" 2>&1 || return 1

    tar xzf "${tgz}" -C /tmp konnect >>"${LOGDIR}/konnect.log" 2>&1 || return 1
    install -m 0755 /tmp/konnect /usr/local/bin/konnect || return 1
    rm -f "${tgz}" /tmp/konnect
}

# libprotobuf-dev is required, not just protobuf-compiler: Ubuntu's
# protobuf-compiler does not ship the well-known descriptors, so the build
# fails with `google/protobuf/any.proto: File not found`. phase_base installs
# both only when this path is selected.
konnect_from_source() {
    export PROTOC=/usr/bin/protoc
    export PROTOC_INCLUDE=/usr/include
    export CARGO_HTTP_CAINFO="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}"

    rm -rf /tmp/konnect-src
    git clone --depth 1 --branch "${KONNECT_VERSION}" \
        https://github.com/mixelpixx/Konnect.git /tmp/konnect-src \
        >"${LOGDIR}/konnect.log" 2>&1 || return 1

    ( cd /tmp/konnect-src && cargo build --release --locked -p konnect ) \
        >>"${LOGDIR}/konnect.log" 2>&1 || return 1

    install -m 0755 /tmp/konnect-src/target/release/konnect /usr/local/bin/konnect || return 1
    rm -rf /tmp/konnect-src   # several GB of build tree
}

phase_konnect() {
    if [ "${MH_KONNECT_FROM_SOURCE}" = "1" ]; then
        konnect_from_source || return $?
    else
        konnect_from_release || return $?
    fi

    konnect --version >>"${LOGDIR}/konnect.log" 2>&1 || return 1

    # Konnect embeds its own KiCad skills and agents (konnect, kicad-schematic,
    # kicad-pcb, kicad-manufacture, kicad-review, kicad-library). `init` writes
    # them under ~/.claude, which is part of the snapshot, so they are present
    # in every session. Our own skills in .claude/skills/ cover the process and
    # defer to these for KiCad mechanics.
    konnect init --client claude >>"${LOGDIR}/konnect.log" 2>&1 || true
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

    # --- hw-kicad-up: live KiCad for Konnect's IPC tools ------------------
    cat > /usr/local/bin/hw-kicad-up <<'EOF'
#!/usr/bin/env bash
# Bring up KiCad with a project open so Konnect's IPC-backed PCB tools work.
# Only needed for live board editing — schematic edits, ERC/DRC and exports
# are all file-based and work without this.
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
# Phase 7 — finalize. Runs from a trap, so a kill at the time budget still
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

if [ "${MH_ENABLE_KONNECT}" = "1" ]; then
    run kicad phase_kicad &
    PID_KICAD=$!
    run konnect phase_konnect &
    PID_KONNECT=$!
else
    _st kicad SKIP "MH_ENABLE_KONNECT=0"
    _st konnect SKIP "MH_ENABLE_KONNECT=0"
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
