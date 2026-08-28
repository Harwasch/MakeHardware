#!/usr/bin/env bash
# SessionStart hook — runs at the start of every session, cloud and local.
# Wired up by the plugin's own hooks/hooks.json, so every project that installs
# the plugin gets it without touching its settings.
#
# The environment snapshot preserves files but not processes, so anything that
# must be *running* is started here rather than in the setup script.
# Deliberately cheap: no installs, no network, no blocking work.
set -uo pipefail
VENV=/opt/hw-py
[ -d "${VENV}" ] || exit 0        # not a provisioned hardware environment

# Make the toolchain visible to plain `python`, `strictdoc`, ... in this session.
export PATH="${VENV}/bin:${PATH}"

# Bring up the virtual display in the background. Live KiCad needs it; nothing
# else does, so a failure here is not worth blocking the session over.
command -v hw-display-start >/dev/null 2>&1 && hw-display-start >/dev/null 2>&1 &

# Surface degraded components once, at the top of the session, so the agent
# knows what it may not rely on.
if [ -f /opt/makehardware/status.json ]; then
    degraded=$(jq -r '.components | to_entries[]
                      | select(.value.state != "PASS")
                      | "\(.key)=\(.value.state)"' \
               /opt/makehardware/status.json 2>/dev/null | paste -sd' ' -)
    [ -n "${degraded}" ] && echo "MakeHardware: degraded components — ${degraded} (run scripts/hw-doctor.sh)"
fi
exit 0
