#!/usr/bin/env bash
# Bring a container up from nothing, when there is no environment to paste into.
#
# WHY THIS IS NOT `hw-repair bootstrap`:
#
#   `hw-repair` ships inside the plugin. A container bare enough to need a
#   bootstrap has no plugin in it, so the command does not exist. The only
#   entry point that works from nothing is a URL:
#
#     curl -fsSL https://raw.githubusercontent.com/Harwasch/MakeHardware/main/env/bootstrap.sh | bash
#
# WHO THIS IS FOR:
#
#   * A Codex or ChatGPT workspace. The plugin manifest imports there, but
#     there is no environment dialog and no setup-script field, so the skills
#     arrive and the tools they name do not.
#   * A local container or VM that is not the cloud environment.
#   * A cloud environment whose build was killed at the time budget.
#
#   It is NOT for a working environment with one degraded phase. That is
#   `hw-repair`, which is targeted and does not re-run the whole build.
#
# WHAT IT CANNOT DO, and this is the part to read before running it:
#
#   It installs into the RUNNING container. On the cloud environment, the
#   snapshot is unchanged, so the next session starts degraded again — use the
#   environment dialog there and treat this as a rescue.
#
#   And it cannot make this session see MCP servers, skills, slash commands or
#   new PATH entries: those are read once when the session starts. Expect to
#   restart the session afterwards. Subprocess tools — ngspice, kicad-cli,
#   gmsh, the Python environment — work the moment it finishes.
#
#   env/bootstrap.sh [--full]     default skips KiCad and magnetics (~1 min)
#                                 --full installs everything (~6 min)
set -uo pipefail

REPO="${MH_REPO:-Harwasch/MakeHardware}"
REF="${MH_REF:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${REF}/env/setup.sh"
WORK="${TMPDIR:-/tmp}/mh-bootstrap"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "must run as root — it installs packages"
command -v curl >/dev/null 2>&1 || die "curl is not installed and is needed to fetch the setup script"

say "MakeHardware bootstrap — ${REPO}@${REF}"
echo

# A container this bare may not have the tools the setup script itself needs.
if ! command -v uv >/dev/null 2>&1 \
   && [ ! -x /root/.local/bin/uv ] && [ ! -x /root/.cargo/bin/uv ]; then
    echo "uv is absent — installing it first (the setup script assumes it)"
    curl -fsSL https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
        || die "could not install uv. Without it the Python environment cannot be built."
fi
export PATH="/root/.local/bin:/root/.cargo/bin:${PATH}"

mkdir -p "${WORK}"
echo "fetching ${RAW}"
curl -fsSL --max-time 120 --retry 3 --retry-delay 2 "${RAW}" -o "${WORK}/setup.sh" \
    || die "could not fetch the setup script. A public raw.githubusercontent.com
  fetch is served at every network level, so this usually means no outbound
  network at all rather than an allowlist problem."
[ -s "${WORK}/setup.sh" ] || die "the fetched setup script is empty"
grep -q '^phase_base()' "${WORK}/setup.sh" \
    || die "the fetched file is not the setup script — check MH_REF=${REF}"

# The heavy phases are off by default. KiCad and Elmer are minutes each and
# both need ppa.launchpadcontent.net, which is the entry people most often do
# not have; failing there should not cost you the Python environment too.
if [ "${FULL}" = 1 ]; then
    export MH_ENABLE_KICAD=1 MH_ENABLE_MAGNETICS=1
    say "running the full build (~6 min)"
else
    export MH_ENABLE_KICAD=0 MH_ENABLE_MAGNETICS=0
    say "running the quick build — base + Python + plugin (~1 min)"
    echo "  KiCad and magnetics are skipped. Add --full for those, or"
    echo "  install them afterwards with \`hw-repair kicad\` and \`hw-repair elmer\`."
fi
# The plugin install writes to /root/.claude, which is exactly what a Codex or
# local container is missing; it is never the thing to skip here.
export MH_ENABLE_PLUGIN="${MH_ENABLE_PLUGIN:-1}"
echo

bash "${WORK}/setup.sh"
rc=$?

echo
say "bootstrap finished (setup exited ${rc})"
echo
# setup.sh is written to exit 0 even when a phase fails, so its status says
# almost nothing. status.json is the real answer.
if [ -s /opt/makehardware/status.json ] && command -v jq >/dev/null 2>&1; then
    jq -r '.components | to_entries[] | "  \(.key): \(.value.state) \(.value.detail // "")"' \
        /opt/makehardware/status.json
else
    echo "  no status.json — the build did not get far enough to write one"
fi
echo
echo "Next:"
echo "  1. RESTART THE SESSION. MCP servers, skills and commands are read once"
echo "     at session start; until you do, they are installed and invisible."
echo "  2. Run \`hw-doctor\` to see what actually landed."
echo "  3. \`hw-repair\` anything still missing."
